"""
System tray / UI layer for Proximity Share.

Provides a minimal Kivy BoxLayout showing:
  - Device name and status
  - List of discovered peers
  - Recent transfer log

Also handles desktop notifications via plyer.
"""

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
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
        self._offers_container: BoxLayout | None = None
        self._pending_offers: dict[str, BoxLayout] = {}

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

        # Pending offers section
        root.add_widget(Label(
            text="[b]Incoming Files:[/b]",
            markup=True,
            size_hint_y=None,
            height=30,
            halign="left",
        ))
        self._offers_container = BoxLayout(orientation="vertical", size_hint_y=None)
        self._offers_container.bind(minimum_height=self._offers_container.setter("height"))
        root.add_widget(self._offers_container)

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

    # ------------------------------------------------------------------
    # Pending offers
    # ------------------------------------------------------------------

    def show_pending_offer(self, offer_id: str, filename: str, filesize: int):
        """Show a pending file offer with accept/reject buttons."""
        def _update(dt):
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=40, spacing=8)

            size_str = f"{filesize / 1024:.1f} KB" if filesize < 1024 * 1024 else f"{filesize / (1024*1024):.1f} MB"
            label = Label(text=f"{filename} ({size_str})", size_hint_x=0.6, halign="left")
            label.bind(size=label.setter("text_size"))

            accept_btn = Button(text="Accept", size_hint_x=0.2)
            accept_btn.bind(on_press=lambda x: self._handle_offer_response(offer_id, True))

            reject_btn = Button(text="Reject", size_hint_x=0.2)
            reject_btn.bind(on_press=lambda x: self._handle_offer_response(offer_id, False))

            row.add_widget(label)
            row.add_widget(accept_btn)
            row.add_widget(reject_btn)

            self._pending_offers[offer_id] = row
            if self._offers_container:
                self._offers_container.add_widget(row)
        Clock.schedule_once(_update, 0)

    def _handle_offer_response(self, offer_id: str, accept: bool):
        """Handle user's accept/reject decision for a file offer."""
        if accept:
            self.app.accept_file_offer(offer_id)
        else:
            self.app.reject_file_offer(offer_id)
        self._remove_offer_widget(offer_id)

    def _remove_offer_widget(self, offer_id: str):
        """Remove the offer widget from the UI."""
        def _update(dt):
            if offer_id in self._pending_offers:
                widget = self._pending_offers.pop(offer_id)
                if self._offers_container and widget.parent:
                    self._offers_container.remove_widget(widget)
        Clock.schedule_once(_update, 0)
