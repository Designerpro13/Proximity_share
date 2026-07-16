"""
Custom binary transfer protocol for Proximity Share.

Wire format per message:
    [4 bytes: msg_type (uint32, network order)]
    [4 bytes: payload_size (uint32, network order)]
    [payload_size bytes: payload]

Connection flow:
    Sender              Receiver
    ──────              ────────
    HANDSHAKE ────────► (validates version/device)
              ◄──────── HANDSHAKE (ack)
    FILE_OFFER ───────► (shows prompt / auto-accepts)
              ◄──────── FILE_ACCEPT or FILE_REJECT
    FILE_DATA ────────► (writes to disk)
              ◄──────── FILE_ACK or ERROR
"""

import json
import base64
import socket
import struct
import threading
import uuid
from typing import Callable

from kivy.logger import Logger

from security.encryption import EncryptionManager
from transfer.container import FileContainer
from utils.config import Config


class TransferProtocol:
    """TCP binary protocol — both server (receive) and client (send) roles."""

    PROTOCOL_VERSION = 2
    # Minimum peer version we accept (inclusive range: MIN..PROTOCOL_VERSION)
    MIN_PROTOCOL_VERSION = 1

    # Message types
    MSG_HANDSHAKE = 0x01
    MSG_FILE_OFFER = 0x02
    MSG_FILE_ACCEPT = 0x03
    MSG_FILE_REJECT = 0x04
    MSG_FILE_DATA = 0x05
    MSG_FILE_ACK = 0x06
    MSG_ERROR = 0xFF

    # Security limits
    MAX_PAYLOAD_SIZE = 500 * 1024 * 1024  # 500 MB max single message payload
    MAX_CONTROL_MSG_SIZE = 64 * 1024  # 64 KB for handshake/offer/ack messages
    CLIENT_SOCKET_TIMEOUT = 30  # seconds per socket operation

    # Connection limits (DoS protection)
    MAX_CONCURRENT_CONNECTIONS = 10
    MAX_PENDING_OFFERS = 20

    def __init__(self, config: Config | None = None):
        self._config = config or Config()
        self._server_socket: socket.socket | None = None
        self._server_thread: threading.Thread | None = None
        self._running = False
        self._active_connections: dict[tuple, socket.socket] = {}
        self._connections_lock = threading.Lock()

        # Pending file offers for manual accept/reject
        self._pending_offers: dict[str, dict] = {}  # offer_id → {"event": Event, "accepted": bool, ...}

        # Callbacks
        self.on_file_received: Callable[[str], None] | None = None
        self.on_file_offer: Callable[[str, str, int], None] | None = None

    # ==================================================================
    # Pending offer management
    # ==================================================================

    def accept_offer(self, offer_id: str):
        """Accept a pending file offer."""
        if offer_id in self._pending_offers:
            self._pending_offers[offer_id]["accepted"] = True
            self._pending_offers[offer_id]["event"].set()

    def reject_offer(self, offer_id: str):
        """Reject a pending file offer."""
        if offer_id in self._pending_offers:
            self._pending_offers[offer_id]["accepted"] = False
            self._pending_offers[offer_id]["event"].set()

    # ==================================================================
    # Server side
    # ==================================================================

    def start_server(self):
        """Start listening for incoming connections."""
        if self._running:
            return

        port = self._config.get_port()
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.settimeout(1.0)  # allow graceful shutdown
            self._server_socket.bind(("0.0.0.0", port))
            self._server_socket.listen(5)

            self._running = True
            self._server_thread = threading.Thread(target=self._server_loop, daemon=True)
            self._server_thread.start()
            Logger.info(f"Proximity: Protocol server listening on port {port}")
        except Exception as e:
            Logger.error(f"Proximity: Failed to start protocol server: {e}")

    def stop_server(self):
        """Gracefully shut down the server."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
        with self._connections_lock:
            for conn in list(self._active_connections.values()):
                try:
                    conn.close()
                except OSError:
                    pass
            self._active_connections.clear()
        Logger.info("Proximity: Protocol server stopped")

    def _server_loop(self):
        while self._running:
            try:
                client_socket, address = self._server_socket.accept()

                # Enforce maximum concurrent connection limit (DoS protection)
                with self._connections_lock:
                    if len(self._active_connections) >= self.MAX_CONCURRENT_CONNECTIONS:
                        Logger.warning(
                            f"Proximity: Connection limit reached ({self.MAX_CONCURRENT_CONNECTIONS}), "
                            f"rejecting {address}"
                        )
                        try:
                            client_socket.close()
                        except OSError:
                            pass
                        continue

                Logger.info(f"Proximity: Incoming connection from {address}")
                threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, address),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    Logger.error("Proximity: Server accept error")
                break

    def _handle_client(self, sock: socket.socket, address: tuple):
        """Handle a single inbound connection through full protocol flow."""
        with self._connections_lock:
            self._active_connections[address] = sock
        # Set per-connection timeout to prevent slowloris / hanging connections
        sock.settimeout(self.CLIENT_SOCKET_TIMEOUT)
        try:
            # --- Expect HANDSHAKE first ---
            msg_type, payload = self._recv_message(sock)
            if msg_type != self.MSG_HANDSHAKE:
                Logger.warning("Proximity: Expected HANDSHAKE, got %s", msg_type)
                return

            # Validate handshake
            try:
                hs = json.loads(payload.decode())
                peer_version = hs.get("version", 0)
                peer_device = hs.get("device", "unknown")
                peer_encryption = hs.get("encryption", False)
                peer_salt_b64 = hs.get("salt", None)
            except (json.JSONDecodeError, UnicodeDecodeError):
                peer_version = 0
                peer_device = "unknown"
                peer_encryption = False
                peer_salt_b64 = None

            # Version range check: must be >= MIN and <= our current version
            if not isinstance(peer_version, (int, float)) or \
               peer_version < self.MIN_PROTOCOL_VERSION or \
               peer_version > self.PROTOCOL_VERSION:
                self._send_message(sock, self.MSG_ERROR, b"incompatible version")
                return

            # Validate field types/sizes (defense against malformed handshakes)
            if not isinstance(peer_device, str) or len(peer_device) > 256:
                peer_device = "unknown"
            if peer_salt_b64 and (not isinstance(peer_salt_b64, str) or len(peer_salt_b64) > 64):
                self._send_message(sock, self.MSG_ERROR, b"invalid salt")
                return

            # Check encryption compatibility
            shared_secret = self._config.get_shared_secret()
            if peer_encryption and not shared_secret:
                self._send_message(sock, self.MSG_ERROR, b"encryption not configured")
                return

            # Create EncryptionManager if peer is using encryption
            encryption = None
            if peer_encryption and peer_salt_b64 and shared_secret:
                peer_salt = base64.b64decode(peer_salt_b64)
                encryption = EncryptionManager(password=shared_secret, salt=peer_salt)

            # Reply with our own handshake
            hs_reply = json.dumps({
                "version": self.PROTOCOL_VERSION,
                "device": self._config.get_device_name(),
            }).encode()
            self._send_message(sock, self.MSG_HANDSHAKE, hs_reply)
            Logger.info(f"Proximity: Handshake OK with '{peer_device}' (v{peer_version})")

            # --- Expect FILE_OFFER ---
            msg_type, payload = self._recv_message(sock)
            if msg_type != self.MSG_FILE_OFFER:
                return

            offer = json.loads(payload.decode())
            filename = offer.get("filename", "unknown")
            filesize = offer.get("size", 0)

            # Validate offer fields
            if not isinstance(filename, str) or len(filename) > 512:
                self._send_message(sock, self.MSG_ERROR, b"invalid filename")
                return
            if not isinstance(filesize, (int, float)) or filesize < 0:
                self._send_message(sock, self.MSG_ERROR, b"invalid file size")
                return

            # Respect auto-accept config
            if self._config.is_auto_accept_enabled():
                self._send_message(sock, self.MSG_FILE_ACCEPT, b"")
                Logger.info(f"Proximity: Auto-accepted '{filename}' ({filesize} bytes)")
            else:
                # Rate-limit pending offers to prevent DoS
                if len(self._pending_offers) >= self.MAX_PENDING_OFFERS:
                    self._send_message(sock, self.MSG_FILE_REJECT, b"too many pending offers")
                    Logger.warning("Proximity: Rejecting offer — pending offers limit reached")
                    return

                # Manual accept/reject - wait for user decision
                offer_id = str(uuid.uuid4())
                event = threading.Event()
                self._pending_offers[offer_id] = {
                    "event": event,
                    "accepted": False,
                    "filename": filename,
                    "size": filesize,
                }

                # Notify UI about the pending offer
                if self.on_file_offer:
                    self.on_file_offer(offer_id, filename, filesize)

                # Wait for user decision with 60s timeout
                decided = event.wait(timeout=60.0)

                offer_data = self._pending_offers.pop(offer_id, None)

                if not decided or not offer_data or not offer_data.get("accepted"):
                    self._send_message(sock, self.MSG_FILE_REJECT, b"")
                    Logger.info(f"Proximity: Rejected '{filename}' (user decision or timeout)")
                    return

                self._send_message(sock, self.MSG_FILE_ACCEPT, b"")
                Logger.info(f"Proximity: User accepted '{filename}' ({filesize} bytes)")

            # --- Expect FILE_DATA ---
            msg_type, payload = self._recv_message(sock)
            if msg_type != self.MSG_FILE_DATA:
                return

            # Decrypt if encryption is active
            if encryption:
                try:
                    decrypted = encryption.decrypt(payload)
                except Exception as e:
                    Logger.error(f"Proximity: Decryption failed: {e}")
                    self._send_message(sock, self.MSG_ERROR, b"decryption failed")
                    return
            else:
                decrypted = payload

            # Deserialize container and save
            container = FileContainer.from_bytes(decrypted)
            shared_folder = self._config.get_shared_folder()
            output_path = container.save_to_file(shared_folder)
            Logger.info(f"Proximity: Saved file → {output_path}")

            # ACK
            self._send_message(sock, self.MSG_FILE_ACK, b"")

            if self.on_file_received:
                self.on_file_received(str(output_path))

        except Exception as e:
            Logger.error(f"Proximity: Client handler error: {e}")
            try:
                self._send_message(sock, self.MSG_ERROR, str(e).encode()[:256])
            except OSError:
                pass
        finally:
            with self._connections_lock:
                self._active_connections.pop(address, None)
            sock.close()

    # ==================================================================
    # Client side (sending)
    # ==================================================================

    def send_file(self, container: FileContainer, target_ip: str, target_port: int | None = None) -> bool:
        """Send a file container to a remote device. Returns True on success."""
        port = target_port or self._config.get_port()
        timeout = self._config.get_connection_timeout()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            sock.connect((target_ip, port))

            # Determine encryption settings
            shared_secret = self._config.get_shared_secret()
            encryption_enabled = bool(shared_secret)
            encryption = None

            # Build HANDSHAKE payload
            hs_data = {
                "version": self.PROTOCOL_VERSION,
                "device": self._config.get_device_name(),
                "encryption": encryption_enabled,
            }

            if encryption_enabled:
                encryption = EncryptionManager(password=shared_secret)
                hs_data["salt"] = base64.b64encode(encryption.salt).decode()

            # --- HANDSHAKE ---
            hs_payload = json.dumps(hs_data).encode()
            self._send_message(sock, self.MSG_HANDSHAKE, hs_payload)

            msg_type, _ = self._recv_message(sock)
            if msg_type != self.MSG_HANDSHAKE:
                Logger.warning("Proximity: Handshake rejected by peer")
                return False

            # --- FILE_OFFER ---
            offer = json.dumps({
                "filename": container.filename,
                "size": len(container.content),
                "mime_type": container.mime_type,
            }).encode()
            self._send_message(sock, self.MSG_FILE_OFFER, offer)

            msg_type, _ = self._recv_message(sock)
            if msg_type == self.MSG_FILE_REJECT:
                Logger.info("Proximity: Peer rejected the file offer")
                return False
            if msg_type != self.MSG_FILE_ACCEPT:
                return False

            # --- FILE_DATA (optionally encrypted) ---
            raw = container.to_bytes()
            if encryption:
                data_to_send = encryption.encrypt(raw)
            else:
                data_to_send = raw
            self._send_message(sock, self.MSG_FILE_DATA, data_to_send)

            # --- Wait for ACK ---
            msg_type, _ = self._recv_message(sock)
            if msg_type == self.MSG_FILE_ACK:
                Logger.info(f"Proximity: '{container.filename}' sent successfully")
                return True

            Logger.warning(f"Proximity: Unexpected response after data: {msg_type}")
            return False

        except Exception as e:
            Logger.error(f"Proximity: Send failed: {e}")
            return False
        finally:
            try:
                sock.close()
            except OSError:
                pass

    # ==================================================================
    # Wire helpers
    # ==================================================================

    def _send_message(self, sock: socket.socket, msg_type: int, payload: bytes):
        """Frame and send a message."""
        header = struct.pack("!II", msg_type, len(payload))
        sock.sendall(header + payload)

    def _recv_message(self, sock: socket.socket) -> tuple[int, bytes]:
        """Read one framed message. Returns (msg_type, payload).

        Security: enforces maximum payload size to prevent OOM attacks.
        """
        header = self._recv_exact(sock, 8)
        if not header:
            raise ConnectionError("Connection closed while reading header")
        msg_type, size = struct.unpack("!II", header)

        # Enforce payload size limits
        if msg_type == self.MSG_FILE_DATA:
            max_size = self.MAX_PAYLOAD_SIZE
        else:
            max_size = self.MAX_CONTROL_MSG_SIZE

        if size > max_size:
            raise ValueError(
                f"Payload size {size} exceeds limit {max_size} for msg_type=0x{msg_type:02X}"
            )

        if size > 0:
            payload = self._recv_exact(sock, size)
            if payload is None:
                raise ConnectionError("Connection closed while reading payload")
        else:
            payload = b""
        return msg_type, payload

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes | None:
        """Receive exactly `size` bytes from socket."""
        buf = bytearray()
        while len(buf) < size:
            chunk = sock.recv(size - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)
