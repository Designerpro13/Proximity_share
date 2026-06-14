"""
Encryption utilities for secure file transfer.

Uses Fernet symmetric encryption with PBKDF2-derived keys.
Supports per-session random salts for proper key isolation.
"""

import os
import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class EncryptionManager:
    """Handles encryption and decryption of file transfers.

    Each instance can operate in two modes:
      - Shared password (for paired devices with a pre-shared secret)
      - Random key (for ephemeral one-time sessions)
    """

    _ITERATIONS = 100_000
    _SALT_SIZE = 16  # 128-bit random salt

    def __init__(self, password: str | None = None, salt: bytes | None = None):
        """
        Args:
            password: Shared secret between device pair. If None, generates a
                      random Fernet key (use `export_key()` to share it).
            salt: Salt bytes used for key derivation. If None and password is
                  provided, a random salt is generated (retrieve via `self.salt`).
        """
        if password:
            self.salt = salt or os.urandom(self._SALT_SIZE)
            self.key = self._derive_key(password, self.salt)
        else:
            self.key = Fernet.generate_key()
            self.salt = None

        self._cipher = Fernet(self.key)

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """Derive a Fernet-compatible key from password + salt."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self._ITERATIONS,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt raw bytes."""
        return self._cipher.encrypt(data)

    def decrypt(self, token: bytes) -> bytes:
        """Decrypt Fernet token back to raw bytes."""
        return self._cipher.decrypt(token)

    def export_key(self) -> bytes:
        """Return the raw Fernet key (for key-exchange scenarios)."""
        return self.key

    def export_salt(self) -> bytes | None:
        """Return the salt (needed by peer to derive the same key)."""
        return self.salt
