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
import socket
import struct
import threading
from typing import Callable

from kivy.logger import Logger

from security.encryption import EncryptionManager
from transfer.container import FileContainer
from utils.config import Config


class TransferProtocol:
    """TCP binary protocol — both server (receive) and client (send) roles."""

    PROTOCOL_VERSION = 2

    # Message types
    MSG_HANDSHAKE = 0x01
    MSG_FILE_OFFER = 0x02
    MSG_FILE_ACCEPT = 0x03
    MSG_FILE_REJECT = 0x04
    MSG_FILE_DATA = 0x05
    MSG_FILE_ACK = 0x06
    MSG_ERROR = 0xFF

    def __init__(self, config: Config | None = None):
        self._config = config or Config()
        self._server_socket: socket.socket | None = None
        self._server_thread: threading.Thread | None = None
        self._running = False
        self._active_connections: dict[tuple, socket.socket] = {}

        # Encryption (shared password from paired devices)
        self._encryption = EncryptionManager(password=self._config.get_device_name())

        # Callbacks
        self.on_file_received: Callable[[str], None] | None = None

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
        self._active_connections[address] = sock
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
            except (json.JSONDecodeError, UnicodeDecodeError):
                peer_version = 0
                peer_device = "unknown"

            if peer_version < 1:
                self._send_message(sock, self.MSG_ERROR, b"incompatible version")
                return

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

            # Respect auto-accept config
            if self._config.is_auto_accept_enabled():
                self._send_message(sock, self.MSG_FILE_ACCEPT, b"")
                Logger.info(f"Proximity: Auto-accepted '{filename}' ({filesize} bytes)")
            else:
                # TODO: hook into UI for user prompt; for now reject
                self._send_message(sock, self.MSG_FILE_REJECT, b"")
                Logger.info(f"Proximity: Rejected '{filename}' (auto-accept disabled)")
                return

            # --- Expect FILE_DATA ---
            msg_type, payload = self._recv_message(sock)
            if msg_type != self.MSG_FILE_DATA:
                return

            # Decrypt
            try:
                decrypted = self._encryption.decrypt(payload)
            except Exception:
                # Fallback: maybe sender didn't encrypt (legacy)
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

            # --- HANDSHAKE ---
            hs_payload = json.dumps({
                "version": self.PROTOCOL_VERSION,
                "device": self._config.get_device_name(),
            }).encode()
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

            # --- FILE_DATA (encrypted) ---
            raw = container.to_bytes()
            encrypted = self._encryption.encrypt(raw)
            self._send_message(sock, self.MSG_FILE_DATA, encrypted)

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
        """Read one framed message. Returns (msg_type, payload)."""
        header = self._recv_exact(sock, 8)
        if not header:
            raise ConnectionError("Connection closed while reading header")
        msg_type, size = struct.unpack("!II", header)
        payload = self._recv_exact(sock, size) if size > 0 else b""
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
