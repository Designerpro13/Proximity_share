"""
Main application class — lifecycle orchestrator for Proximity Share.

Wires together: Config, NetworkDiscovery, TransferManager, SystemTrayManager.
"""

from kivy.app import App
from kivy.clock import Clock
from kivy.logger import Logger

from network.discovery import NetworkDiscovery
from transfer.manager import TransferManager
from ui.system_tray import SystemTrayManager
from utils.config import Config


class ProximityShareApp(App):
    """Kivy application entry point."""

    title = "Proximity Share"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config_manager = Config()
        self.network_discovery: NetworkDiscovery | None = None
        self.transfer_manager: TransferManager | None = None
        self.system_tray: SystemTrayManager | None = None

    # ------------------------------------------------------------------
    # Kivy lifecycle
    # ------------------------------------------------------------------

    def build(self):
        Logger.info("Proximity: Building application")

        # Create components
        self.network_discovery = NetworkDiscovery(self.config_manager)
        self.transfer_manager = TransferManager(self.config_manager)
        self.system_tray = SystemTrayManager(self)

        # Wire callbacks
        self.network_discovery.on_devices_changed = self._on_devices_changed
        self.transfer_manager.on_file_received = self._on_file_received
        self.transfer_manager.on_file_sent = self._on_file_sent
        self.transfer_manager.on_file_offer = self._on_file_offer

        # Kick off services after the event loop starts
        Clock.schedule_once(self._start_services, 0.5)

        # Periodic device list refresh (in case callbacks miss something)
        Clock.schedule_interval(self._refresh_devices, 10)

        return self.system_tray.get_root_widget()

    def _start_services(self, dt):
        """Start background services."""
        self.network_discovery.start()
        self.transfer_manager.start()
        self.system_tray.set_status("Running — listening for devices")
        Logger.info("Proximity: All services started")

    def on_stop(self):
        """Clean shutdown."""
        Logger.info("Proximity: Shutting down")
        if self.network_discovery:
            self.network_discovery.stop()
        if self.transfer_manager:
            self.transfer_manager.stop()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_devices_changed(self):
        """Called by NetworkDiscovery when the peer list changes."""
        self._refresh_devices(0)

    def _refresh_devices(self, dt):
        """Push current device list to the UI."""
        if self.network_discovery and self.system_tray:
            devices = self.network_discovery.get_discovered_devices()
            self.system_tray.update_devices(devices)

    def _on_file_received(self, filepath: str):
        """Called by TransferManager/Protocol when a file arrives."""
        from pathlib import Path
        name = Path(filepath).name
        if self.system_tray:
            self.system_tray.notify_file_received(name)

    def _on_file_sent(self, filename: str, target_ip: str):
        """Called by TransferManager when a file is successfully sent."""
        if self.system_tray:
            self.system_tray.notify_file_sent(filename, target_ip)

    def _on_file_offer(self, offer_id: str, filename: str, filesize: int):
        """Called when a file offer arrives and auto-accept is disabled."""
        if self.system_tray:
            self.system_tray.show_pending_offer(offer_id, filename, filesize)

    def accept_file_offer(self, offer_id: str):
        """Accept an incoming file offer."""
        if self.transfer_manager:
            self.transfer_manager.accept_offer(offer_id)

    def reject_file_offer(self, offer_id: str):
        """Reject an incoming file offer."""
        if self.transfer_manager:
            self.transfer_manager.reject_offer(offer_id)

    # ------------------------------------------------------------------
    # Public API (for external callers / future CLI)
    # ------------------------------------------------------------------

    def send_file(self, file_path: str, target_ip: str, target_port: int | None = None) -> bool:
        """Queue a file for sending to a discovered device."""
        if not self.transfer_manager:
            return False
        return self.transfer_manager.queue_file(file_path, target_ip, target_port)

    def get_devices(self) -> dict:
        """Return currently discovered devices."""
        if not self.network_discovery:
            return {}
        return self.network_discovery.get_discovered_devices()
