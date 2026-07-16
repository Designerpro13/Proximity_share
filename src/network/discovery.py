"""
Network discovery using mDNS (zeroconf) for automatic device detection.

Advertises this device on the local network and discovers peers running
the same service type.
"""

import socket
import threading
from typing import Callable

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf, ServiceInfo, IPVersion
from kivy.logger import Logger

from utils.config import Config


class P2PServiceListener(ServiceListener):
    """Callback handler for zeroconf service events."""

    def __init__(self, on_add: Callable, on_remove: Callable):
        self._on_add = on_add
        self._on_remove = on_remove

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info:
            self._on_add(info)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._on_remove(name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info:
            self._on_add(info)


class NetworkDiscovery:
    """Handles mDNS service advertisement and browsing.

    Discovered devices are stored as a dict mapping service name → ServiceInfo.
    """

    SERVICE_TYPE = "_proximityshare._tcp.local."

    def __init__(self, config: Config | None = None):
        self._config = config or Config()
        self.zeroconf: Zeroconf | None = None
        self.browser: ServiceBrowser | None = None
        self.service_info: ServiceInfo | None = None
        self.discovered_devices: dict[str, ServiceInfo] = {}
        self._lock = threading.Lock()
        self.running = False

        # Optional callback for UI updates
        self.on_devices_changed: Callable | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start advertising and browsing."""
        if self.running:
            return

        try:
            self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self._register_service()

            listener = P2PServiceListener(
                on_add=self._on_device_discovered,
                on_remove=self._on_device_removed,
            )
            self.browser = ServiceBrowser(self.zeroconf, self.SERVICE_TYPE, listener)
            self.running = True
            Logger.info("Proximity: Network discovery started")
        except Exception as e:
            Logger.error(f"Proximity: Failed to start network discovery: {e}")

    def stop(self):
        """Unregister and tear down."""
        if not self.running:
            return
        try:
            if self.service_info and self.zeroconf:
                self.zeroconf.unregister_service(self.service_info)
            if self.zeroconf:
                self.zeroconf.close()
            self.running = False
            Logger.info("Proximity: Network discovery stopped")
        except Exception as e:
            Logger.error(f"Proximity: Error stopping network discovery: {e}")

    # ------------------------------------------------------------------
    # Service registration
    # ------------------------------------------------------------------

    def _get_local_ip(self) -> str:
        """Best-effort detection of local LAN IP (not 127.0.0.1)."""
        try:
            # Connect to a non-routable address to discover the preferred source IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def _register_service(self):
        """Register this device on the network.

        Security: Uses a display name in mDNS properties rather than
        the raw hostname to reduce information leakage to the LAN.
        """
        device_name = self._config.get_device_name()
        port = self._config.get_port()
        local_ip = self._get_local_ip()

        # Use a sanitized display name (strip domain components if present)
        display_name = device_name.split(".")[0] if device_name else "peer"

        self.service_info = ServiceInfo(
            self.SERVICE_TYPE,
            f"{display_name}.{self.SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip)],
            port=port,
            properties={
                "version": "2",
                "device": display_name,
            },
        )
        self.zeroconf.register_service(self.service_info)
        Logger.info(f"Proximity: Registered as '{display_name}' at {local_ip}:{port}")

    # ------------------------------------------------------------------
    # Device callbacks
    # ------------------------------------------------------------------

    def _on_device_discovered(self, info: ServiceInfo):
        with self._lock:
            name = info.name
            # Skip our own service
            if self.service_info and name == self.service_info.name:
                return
            self.discovered_devices[name] = info
            Logger.info(f"Proximity: Discovered device: {name}")
        if self.on_devices_changed:
            self.on_devices_changed()

    def _on_device_removed(self, name: str):
        notify = False
        with self._lock:
            if name in self.discovered_devices:
                del self.discovered_devices[name]
                Logger.info(f"Proximity: Device removed: {name}")
                notify = True
        if notify and self.on_devices_changed:
            self.on_devices_changed()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_discovered_devices(self) -> dict[str, dict]:
        """Return a simplified dict of discovered devices.

        Returns:
            {friendly_name: {"ip": str, "port": int}}
        """
        devices = {}
        with self._lock:
            for name, info in self.discovered_devices.items():
                addresses = info.parsed_addresses()
                ip = addresses[0] if addresses else None
                if ip:
                    # Extract friendly name from properties or service name
                    props = info.properties or {}
                    friendly = props.get(b"device", b"").decode() or name.split(".")[0]
                    devices[friendly] = {"ip": ip, "port": info.port}
        return devices
