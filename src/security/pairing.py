"""
Device pairing — automatic secure shared secret establishment.

Implements a TOFU (Trust On First Use) pairing flow using a short
numeric PIN displayed on-screen for out-of-band verification:

    1. Device A discovers Device B on the LAN
    2. Device A initiates pairing → generates a random shared secret
    3. Device A derives a 6-digit PIN from the secret
    4. Device A displays the PIN on screen
    5. User reads PIN from A and enters it on Device B (or confirms match)
    6. Both devices store the shared secret in their paired_devices registry
    7. All future connections use this secret for mutual authentication

The paired_devices registry is stored at:
    ~/.proximity_share/paired_devices.json

Format:
    {
        "device_name": {
            "secret": "<base64-encoded shared secret>",
            "paired_at": "<ISO timestamp>",
            "last_seen": "<ISO timestamp>"
        }
    }
"""

import hashlib
import json
import os
import base64
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from kivy.logger import Logger


class PairingManager:
    """Manages device pairing and the paired devices registry."""

    PIN_LENGTH = 6
    SECRET_LENGTH = 32  # 256-bit shared secret

    def __init__(self, config_dir: Path | None = None):
        self._config_dir = config_dir or Path.home() / ".proximity_share"
        self._registry_file = self._config_dir / "paired_devices.json"
        self._registry: dict[str, dict] = self._load_registry()
        self._lock = threading.Lock()

        # Active pairing session state
        self._pairing_secret: str | None = None
        self._pairing_pin: str | None = None
        self._pairing_device: str | None = None
        self._pairing_event: threading.Event | None = None
        self._pairing_confirmed: bool = False

        # Callbacks
        self.on_pairing_request: Callable[[str, str], None] | None = None  # (device_name, pin)
        self.on_pairing_complete: Callable[[str], None] | None = None  # (device_name)

    # ------------------------------------------------------------------
    # Registry management
    # ------------------------------------------------------------------

    def _load_registry(self) -> dict:
        """Load paired devices from disk."""
        if self._registry_file.exists():
            try:
                with open(self._registry_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_registry(self):
        """Persist paired devices to disk."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        with open(self._registry_file, "w") as f:
            json.dump(self._registry, f, indent=2)

    def get_secret_for_device(self, device_name: str) -> str:
        """Get the shared secret for a paired device. Empty string if not paired."""
        with self._lock:
            entry = self._registry.get(device_name)
            if entry:
                return entry.get("secret", "")
        return ""

    def is_device_paired(self, device_name: str) -> bool:
        """Check if a device is in the paired registry."""
        with self._lock:
            return device_name in self._registry

    def get_paired_devices(self) -> list[str]:
        """Return list of paired device names."""
        with self._lock:
            return list(self._registry.keys())

    def unpair_device(self, device_name: str):
        """Remove a device from the paired registry."""
        with self._lock:
            if device_name in self._registry:
                del self._registry[device_name]
                self._save_registry()
                Logger.info(f"Proximity: Unpaired from '{device_name}'")

    def update_last_seen(self, device_name: str):
        """Update last_seen timestamp for a paired device."""
        with self._lock:
            if device_name in self._registry:
                self._registry[device_name]["last_seen"] = datetime.now(timezone.utc).isoformat()
                self._save_registry()

    # ------------------------------------------------------------------
    # Pairing initiation (this device starts pairing)
    # ------------------------------------------------------------------

    def initiate_pairing(self) -> tuple[str, str]:
        """Generate a new pairing secret and derive a PIN.

        Returns:
            (secret_b64, pin) — the base64 secret and 6-digit PIN
        """
        raw_secret = os.urandom(self.SECRET_LENGTH)
        secret_b64 = base64.b64encode(raw_secret).decode()
        pin = self._derive_pin(raw_secret)

        self._pairing_secret = secret_b64
        self._pairing_pin = pin
        self._pairing_event = threading.Event()
        self._pairing_confirmed = False

        Logger.info(f"Proximity: Pairing initiated — PIN: {pin}")
        return secret_b64, pin

    def complete_pairing(self, device_name: str, secret_b64: str):
        """Store a completed pairing in the registry.

        Called after both sides confirm the PIN matches.
        """
        with self._lock:
            self._registry[device_name] = {
                "secret": secret_b64,
                "paired_at": datetime.now(timezone.utc).isoformat(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }
            self._save_registry()
        Logger.info(f"Proximity: Paired with '{device_name}' successfully")

        if self.on_pairing_complete:
            self.on_pairing_complete(device_name)

    # ------------------------------------------------------------------
    # Pairing acceptance (remote device wants to pair with us)
    # ------------------------------------------------------------------

    def receive_pairing_request(self, device_name: str, pin: str) -> bool:
        """Handle an incoming pairing request.

        Displays the PIN to the user and waits for confirmation.
        Returns True if user confirmed, False if rejected/timeout.
        """
        self._pairing_device = device_name
        self._pairing_pin = pin
        self._pairing_event = threading.Event()
        self._pairing_confirmed = False

        # Notify UI to show pairing dialog
        if self.on_pairing_request:
            self.on_pairing_request(device_name, pin)

        # Wait for user decision (60s timeout)
        decided = self._pairing_event.wait(timeout=60.0)
        return decided and self._pairing_confirmed

    def confirm_pairing(self):
        """User confirms the displayed PIN matches."""
        self._pairing_confirmed = True
        if self._pairing_event:
            self._pairing_event.set()

    def reject_pairing(self):
        """User rejects the pairing request."""
        self._pairing_confirmed = False
        if self._pairing_event:
            self._pairing_event.set()

    # ------------------------------------------------------------------
    # PIN derivation
    # ------------------------------------------------------------------

    @classmethod
    def _derive_pin(cls, secret: bytes) -> str:
        """Derive a numeric PIN from a secret (deterministic).

        Uses SHA-256 and takes modulo to get N digits.
        """
        digest = hashlib.sha256(secret).digest()
        # Use first 4 bytes as an integer, modulo 10^PIN_LENGTH
        num = int.from_bytes(digest[:4], "big") % (10 ** cls.PIN_LENGTH)
        return str(num).zfill(cls.PIN_LENGTH)

    @classmethod
    def verify_pin(cls, secret_b64: str, pin: str) -> bool:
        """Verify that a PIN matches a given secret."""
        try:
            raw_secret = base64.b64decode(secret_b64)
            return cls._derive_pin(raw_secret) == pin
        except Exception:
            return False
