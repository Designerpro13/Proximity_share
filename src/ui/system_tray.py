"""
System tray / UI layer for Proximity Share.

Provides a minimal Kivy BoxLayout showing:
  - Device name and status
  - List of discovered peers
  - Recent transfer log

Also handles desktop notifications via plyer.
"""

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock
from kivy.logger import Logger

try:
    from plyer import notification as _plyer_notification
except ImportError:
    _plyer_notification = None


class SystemTrayManager:
    """Manages the root Kivy widget and desktop notifications."""

    MAX_LOG_LINES = 50

    def __init__(self, app):
        self.app = app
        self._root: BoxLayout | None = None
        self._status_label: Label | None = None
        self._devices_label: Label | None = None
        self._log_label: Label | None = None
        self._log_lines: list[str] = []

    # ------------------------------------------------------------------
    # Widget construction
    # ------------------------------------------------------------------

    def get_root_widget(self) -> BoxLayout:
        """Build and return the root widget."""
        if self._root:
            return self._root

        root = BoxLayout(orientation="vertical", padding=16, spacing=12)

        # Header
        self._status_label = Label(
            text="[b]Proximity Share[/b]\nStarting...",
            markup=True,
            size_hint_y=None,
            height=60,
            halign="center",
            valign="middle",
        )
        self._status_label.bind(size=self._status_label.setter("text_size"))
        root.add_widget(self._status_label)

        # Devices section
        self._devices_label = Label(
            text="[b]Devices:[/b] scanning...",
            markup=True,
            size_hint_y=None,
            height=80,
            halign="left",
            valign="top",
        )
        self._devices_label.bind(size=self._devices_label.setter("text_size"))
        root.add_widget(self._devices_label)

        # Transfer log (scrollable)
        scroll = ScrollView(size_hint=(1, 1))
        self._log_label = Label(
            text="",
            markup=True,
            size_hint_y=None,
            halign="left",
            valign="top",
        )
        self._log_label.bind(texture_size=self._log_label.setter("size"))
        self._log_label.bind(size=self._log_label.setter("text_size"))
        scroll.add_widget(self._log_label)
        root.add_widget(scroll)

        self._root = root
        return root

    # ------------------------------------------------------------------
    # UI updates (call from main thread via Clock)
    # ------------------------------------------------------------------

    def set_status(self, text: str):
        """Update the status header."""
        def _update(dt):
            if self._status_label:
                self._status_label.text = f"[b]Proximity Share[/b]\n{text}"
        Clock.schedule_once(_update, 0)

    def update_devices(self, devices: dict[str, dict]):
        """Refresh the discovered devices display.

        Args:
            devices: {name: {"ip": str, "port": int}}
        """
        def _update(dt):
            if not self._devices_label:
                return
            if not devices:
                self._devices_label.text = "[b]Devices:[/b] none found"
                return
            lines = [f"  • {name} ({info['ip']})" for name, info in devices.items()]
            self._devices_label.text = "[b]Devices:[/b]\n" + "\n".join(lines)
        Clock.schedule_once(_update, 0)

    def log_event(self, message: str):
        """Append a line to the transfer log."""
        def _update(dt):
            self._log_lines.append(message)
            if len(self._log_lines) > self.MAX_LOG_LINES:
                self._log_lines = self._log_lines[-self.MAX_LOG_LINES:]
            if self._log_label:
                self._log_label.text = "\n".join(self._log_lines)
        Clock.schedule_once(_update, 0)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def show_notification(self, title: str, message: str):
        """Show a desktop notification (best-effort)."""
        if not _plyer_notification:
            return
        try:
            _plyer_notification.notify(
                title=title,
                message=message,
                app_name="Proximity Share",
                timeout=5,
            )
        except Exception as e:
            Logger.error(f"Proximity: Notification failed: {e}")

    def notify_file_received(self, filename: str):
        self.log_event(f"↓ Received: {filename}")
        self.show_notification("File Received", f"Received: {filename}")

    def notify_file_sent(self, filename: str, device: str):
        self.log_event(f"↑ Sent: {filename} → {device}")
        self.show_notification("File Sent", f"Sent {filename} to {device}")

    def notify_error(self, message: str):
        self.log_event(f"✗ Error: {message}")
