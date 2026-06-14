"""
Configuration management for Proximity Share.

Loads defaults from config/app.ini (if present), then overlays
user-specific settings from ~/.proximity_share/config.json.
"""

import json
import os
import platform
import socket
import configparser
from pathlib import Path


def _get_device_name() -> str:
    """Cross-platform device name detection."""
    # Try hostname first (works everywhere)
    name = socket.gethostname()
    if name and name != "localhost":
        return name
    # Fallback to env vars
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or platform.node() or "Unknown"


class Config:
    """Configuration manager.

    Priority (highest wins):
        1. User JSON (~/.proximity_share/config.json)
        2. Static INI  (config/app.ini)
        3. Hardcoded defaults
    """

    # Locate project root (two levels up from this file: src/utils/config.py → project root)
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    _INI_PATH = _PROJECT_ROOT / "config" / "app.ini"

    def __init__(self):
        self.config_dir = Path.home() / ".proximity_share"
        self.config_file = self.config_dir / "config.json"
        self._defaults = self._hardcoded_defaults()
        self._ini_values = self._load_ini()
        self._user_values = self._load_json()
        # Merged view: defaults < ini < user json
        self.config_data = {**self._defaults, **self._ini_values, **self._user_values}

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hardcoded_defaults() -> dict:
        return {
            "shared_folder": str(Path.home() / "Proximity_Shared"),
            "max_retries": 10,
            "port": 8888,
            "device_name": _get_device_name(),
            "auto_accept_files": True,
            "notification_enabled": True,
            "buffer_size": 8192,
            "connection_timeout": 10,
            "discovery_interval": 30,
            "retry_base_delay": 30,
            "max_retry_delay": 1800,
        }

    @classmethod
    def _load_ini(cls) -> dict:
        """Parse config/app.ini into a flat dict (type-coerced)."""
        result: dict = {}
        if not cls._INI_PATH.exists():
            return result

        parser = configparser.ConfigParser()
        parser.read(cls._INI_PATH)

        # Map INI keys → config_data keys
        mapping = {
            ("network", "default_port"): ("port", int),
            ("network", "discovery_interval"): ("discovery_interval", int),
            ("network", "connection_timeout"): ("connection_timeout", int),
            ("transfer", "max_retries"): ("max_retries", int),
            ("transfer", "retry_base_delay"): ("retry_base_delay", int),
            ("transfer", "max_retry_delay"): ("max_retry_delay", int),
            ("transfer", "buffer_size"): ("buffer_size", int),
            ("ui", "show_notifications"): ("notification_enabled", lambda v: v.lower() == "true"),
        }

        for (section, key), (target_key, coerce) in mapping.items():
            try:
                raw = parser.get(section, key)
                result[target_key] = coerce(raw)
            except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
                pass

        return result

    def _load_json(self) -> dict:
        """Load user overrides from JSON file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_config(self):
        """Persist current config to user JSON."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self.config_data, f, indent=2)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_shared_folder(self) -> Path:
        folder = Path(self.config_data["shared_folder"])
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def get_device_name(self) -> str:
        return self.config_data["device_name"]

    def get_port(self) -> int:
        return int(self.config_data["port"])

    def get_max_retries(self) -> int:
        return int(self.config_data["max_retries"])

    def get_buffer_size(self) -> int:
        return int(self.config_data["buffer_size"])

    def get_connection_timeout(self) -> int:
        return int(self.config_data["connection_timeout"])

    def get_retry_base_delay(self) -> int:
        return int(self.config_data["retry_base_delay"])

    def get_max_retry_delay(self) -> int:
        return int(self.config_data["max_retry_delay"])

    def is_auto_accept_enabled(self) -> bool:
        return bool(self.config_data.get("auto_accept_files", True))

    def is_notification_enabled(self) -> bool:
        return bool(self.config_data.get("notification_enabled", True))
