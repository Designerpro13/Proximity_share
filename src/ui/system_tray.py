"""
UI layer for Proximity Share.

Provides a Kivy BoxLayout showing:
  - Device name and status
  - List of discovered peers (clickable to select target)
  - Send File button + Pair Device button
  - Pending incoming file offers
  - Recent transfer log

Also handles desktop notifications via plyer.
"""

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.textinput import TextInput
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
        self._devices_layout: BoxLayout | None = None
        self._log_label: Label | None = None
        self._log_lines: list[str] = []
        self._offers_container: BoxLayout | None = None
        self._pending_offers: dict[str, BoxLayout] = {}
        self._selected_device: str | None = None
        self._device_buttons: dict[str, Button] = {}

    # ------------------------------------------------------------------
    # Widget construction
    # ------------------------------------------------------------------

    def get_root_widget(self) -> BoxLayout:
        """Build and return the root widget."""
        if self._root:
            return self._root

        root = BoxLayout(orientation="vertical", padding=12, spacing=8)

        # Header
        self._status_label = Label(
            text="[b]Proximity Share[/b]\nStarting...",
            markup=True,
            size_hint_y=None,
            height=50,
            halign="center",
            valign="middle",
        )
        self._status_label.bind(size=self._status_label.setter("text_size"))
        root.add_widget(self._status_label)

        # ─── Action buttons row ───
        actions = BoxLayout(orientation="horizontal", size_hint_y=None, height=44, spacing=8)

        send_btn = Button(text=" Send File", size_hint_x=0.5)
        send_btn.bind(on_press=lambda x: self._open_file_chooser())

        pair_btn = Button(text=" Pair Device", size_hint_x=0.5)
        pair_btn.bind(on_press=lambda x: self._open_pair_dialog())

        actions.add_widget(send_btn)
        actions.add_widget(pair_btn)
        root.add_widget(actions)

        # ─── Devices section (clickable list) ───
        devices_header = Label(
            text="[b]Devices[/b] (tap to select target):",
            markup=True,
            size_hint_y=None,
            height=28,
            halign="left",
        )
        devices_header.bind(size=devices_header.setter("text_size"))
        root.add_widget(devices_header)

        self._devices_layout = BoxLayout(orientation="vertical", size_hint_y=None, height=0)
        self._devices_layout.bind(minimum_height=self._devices_layout.setter("height"))
        root.add_widget(self._devices_layout)

        # ─── Incoming files section ───
        offers_header = Label(
            text="[b]Incoming:[/b]",
            markup=True,
            size_hint_y=None,
            height=24,
            halign="left",
        )
        offers_header.bind(size=offers_header.setter("text_size"))
        root.add_widget(offers_header)

        self._offers_container = BoxLayout(orientation="vertical", size_hint_y=None)
        self._offers_container.bind(minimum_height=self._offers_container.setter("height"))
        root.add_widget(self._offers_container)

        # ─── Transfer log (scrollable) ───
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
    # UI updates
    # ------------------------------------------------------------------

    def set_status(self, text: str):
        """Update the status header."""
        def _update(dt):
            if self._status_label:
                self._status_label.text = f"[b]Proximity Share[/b]\n{text}"
        Clock.schedule_once(_update, 0)

    def update_devices(self, devices: dict[str, dict]):
        """Refresh the discovered devices as clickable buttons."""
        def _update(dt):
            if not self._devices_layout:
                return
            self._devices_layout.clear_widgets()
            self._device_buttons.clear()

            if not devices:
                lbl = Label(text="  No devices found", size_hint_y=None, height=30, halign="left")
                lbl.bind(size=lbl.setter("text_size"))
                self._devices_layout.add_widget(lbl)
                self._devices_layout.height = 30
                return

            for name, info in devices.items():
                ip = info["ip"]
                selected = (name == self._selected_device)
                prefix = "▶ " if selected else "  "
                btn = Button(
                    text=f"{prefix}{name} ({ip})",
                    size_hint_y=None,
                    height=36,
                    halign="left",
                    background_color=(0.2, 0.6, 0.2, 1) if selected else (0.3, 0.3, 0.3, 1),
                )
                btn.bind(on_press=lambda x, n=name: self._select_device(n))
                self._device_buttons[name] = btn
                self._devices_layout.add_widget(btn)

            self._devices_layout.height = len(devices) * 36
        Clock.schedule_once(_update, 0)

    def _select_device(self, device_name: str):
        """Select a device as the send target."""
        self._selected_device = device_name
        self.log_event(f"→ Target: {device_name}")
        # Refresh to show selection highlight
        devices = self.app.get_devices()
        self.update_devices(devices)

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
    # Send File dialog
    # ------------------------------------------------------------------

    def _open_file_chooser(self):
        """Open a file picker popup."""
        if not self._selected_device:
            self.log_event("✗ Select a device first (tap a device above)")
            return

        content = BoxLayout(orientation="vertical", spacing=8)
        chooser = FileChooserListView(
            path=str(self.app.config_manager.get_shared_folder().parent),
            filters=["*"],
        )
        content.add_widget(chooser)

        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        send_btn = Button(text="Send")
        cancel_btn = Button(text="Cancel")
        btn_row.add_widget(send_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)

        popup = Popup(title="Select file to send", content=content, size_hint=(0.9, 0.9))

        def _send(instance):
            selection = chooser.selection
            if selection:
                filepath = selection[0]
                devices = self.app.get_devices()
                target = devices.get(self._selected_device)
                if target:
                    success = self.app.send_file(filepath, target["ip"], target["port"])
                    if success:
                        from pathlib import Path
                        self.log_event(f"↑ Queued: {Path(filepath).name} → {self._selected_device}")
                    else:
                        self.log_event(f"✗ Failed to queue file")
                else:
                    self.log_event(f"✗ Device '{self._selected_device}' not available")
            popup.dismiss()

        send_btn.bind(on_press=_send)
        cancel_btn.bind(on_press=lambda x: popup.dismiss())
        popup.open()

    # ------------------------------------------------------------------
    # Pair Device dialog
    # ------------------------------------------------------------------

    def _open_pair_dialog(self):
        """Open pairing options popup."""
        content = BoxLayout(orientation="vertical", spacing=12, padding=12)

        content.add_widget(Label(
            text="[b]Device Pairing[/b]",
            markup=True,
            size_hint_y=None,
            height=30,
        ))

        # Option 1: Start pairing (show PIN)
        start_btn = Button(text="Start Pairing (show my PIN)", size_hint_y=None, height=44)

        # Option 2: Enter peer's PIN
        enter_label = Label(text="Or enter peer's PIN:", size_hint_y=None, height=28)
        pin_input = TextInput(
            hint_text="6-digit PIN",
            input_filter="int",
            multiline=False,
            size_hint_y=None,
            height=40,
        )
        # Limit to 6 characters via on_text handler
        def _limit_pin_length(instance, value):
            if len(value) > 6:
                instance.text = value[:6]
        pin_input.bind(text=_limit_pin_length)
        confirm_btn = Button(text="Confirm PIN", size_hint_y=None, height=44)

        cancel_btn = Button(text="Close", size_hint_y=None, height=36)

        content.add_widget(start_btn)
        content.add_widget(Label(size_hint_y=None, height=8))  # spacer
        content.add_widget(enter_label)
        content.add_widget(pin_input)
        content.add_widget(confirm_btn)
        content.add_widget(Label(size_hint_y=1))  # flex spacer
        content.add_widget(cancel_btn)

        popup = Popup(title="Pair Device", content=content, size_hint=(0.7, 0.6))

        def _start_pairing(instance):
            pin = self.app.start_pairing()
            if pin:
                self.log_event(f" Your pairing PIN: [b]{pin}[/b]")
                self.show_notification("Pairing PIN", f"Your PIN: {pin}")
                start_btn.text = f"PIN: {pin}"
                start_btn.disabled = True

        def _confirm_pin(instance):
            entered = pin_input.text.strip()
            if len(entered) == 6 and entered.isdigit():
                # For now, use entered PIN to complete pairing with selected device
                if self._selected_device:
                    self.app.complete_pairing_with_pin(self._selected_device, entered)
                    self.log_event(f" Pairing with '{self._selected_device}' via PIN")
                else:
                    self.log_event("✗ Select a device first to pair with")
                popup.dismiss()
            else:
                pin_input.hint_text = "Must be 6 digits!"

        start_btn.bind(on_press=_start_pairing)
        confirm_btn.bind(on_press=_confirm_pin)
        cancel_btn.bind(on_press=lambda x: popup.dismiss())
        popup.open()

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

    # ------------------------------------------------------------------
    # Pairing UI
    # ------------------------------------------------------------------

    def show_pairing_pin(self, pin: str, device_name: str | None = None):
        """Display the pairing PIN for the user to share with the peer."""
        def _update(dt):
            context = f" for '{device_name}'" if device_name else ""
            self.log_event(f" Pairing PIN{context}: [b]{pin}[/b] — share with peer")
            self.show_notification("Pairing", f"PIN: {pin}")
        Clock.schedule_once(_update, 0)

    def show_pairing_request(self, device_name: str, pin: str):
        """Show incoming pairing request with confirm/reject buttons."""
        def _update(dt):
            if not self._offers_container:
                return
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=50, spacing=8)

            label = Label(
                text=f" Pair '{device_name}'? PIN: [b]{pin}[/b]",
                markup=True,
                size_hint_x=0.6,
                halign="left",
            )
            label.bind(size=label.setter("text_size"))

            confirm_btn = Button(text="Confirm", size_hint_x=0.2)
            confirm_btn.bind(on_press=lambda x: self._handle_pairing_response(True, row))

            reject_btn = Button(text="Reject", size_hint_x=0.2)
            reject_btn.bind(on_press=lambda x: self._handle_pairing_response(False, row))

            row.add_widget(label)
            row.add_widget(confirm_btn)
            row.add_widget(reject_btn)

            self._offers_container.add_widget(row)
        Clock.schedule_once(_update, 0)

    def _handle_pairing_response(self, confirm: bool, widget: BoxLayout):
        """Handle user pairing confirmation/rejection."""
        if confirm:
            self.app.confirm_pairing()
        else:
            self.app.reject_pairing()

        def _remove(dt):
            if self._offers_container and widget.parent:
                self._offers_container.remove_widget(widget)
        Clock.schedule_once(_remove, 0)

    def notify_paired(self, device_name: str):
        """Notify user that pairing completed."""
        self.log_event(f"✓ Paired with '{device_name}'")
        self.show_notification("Paired", f"Now paired with {device_name}")
