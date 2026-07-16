"""
Encryption and authentication utilities for secure file transfer.

Uses Fernet symmetric encryption with PBKDF2-derived keys.
Supports per-session random salts for proper key isolation.
Provides HMAC-based message authentication and challenge-response verification.
"""

import os
import hmac
import hashlib
import base64
import time

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
            # Derive a separate HMAC key (using different context)
            self._hmac_key = self._derive_hmac_key(password, self.salt)
        else:
            self.key = Fernet.generate_key()
            self.salt = None
            self._hmac_key = os.urandom(32)

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

    def _derive_hmac_key(self, password: str, salt: bytes) -> bytes:
        """Derive a separate HMAC key (different from encryption key)."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt + b"hmac",  # Different context than encryption key
            iterations=self._ITERATIONS,
        )
        return kdf.derive(password.encode())

    # ------------------------------------------------------------------
    # Public API — Encryption
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

    # ------------------------------------------------------------------
    # Public API — Authentication (HMAC + Challenge-Response)
    # ------------------------------------------------------------------

    def compute_hmac(self, data: bytes) -> bytes:
        """Compute HMAC-SHA256 for message authentication."""
        return hmac.new(self._hmac_key, data, hashlib.sha256).digest()

    def verify_hmac(self, data: bytes, tag: bytes) -> bool:
        """Verify an HMAC tag (constant-time comparison)."""
        expected = hmac.new(self._hmac_key, data, hashlib.sha256).digest()
        return hmac.compare_digest(expected, tag)

    @staticmethod
    def generate_challenge() -> bytes:
        """Generate a 32-byte random challenge for authentication."""
        return os.urandom(32)

    def solve_challenge(self, challenge: bytes) -> bytes:
        """Produce a response proving knowledge of the shared secret.

        Response = HMAC-SHA256(hmac_key, challenge || timestamp_window)
        The timestamp window (floored to 30s) prevents replay outside that window.
        """
        # Floor timestamp to 30-second window for clock tolerance
        window = str(int(time.time()) // 30).encode()
        return hmac.new(self._hmac_key, challenge + window, hashlib.sha256).digest()

    def verify_challenge_response(self, challenge: bytes, response: bytes) -> bool:
        """Verify a challenge response, allowing ±1 time window for clock skew."""
        current_window = int(time.time()) // 30
        for offset in (0, -1, 1):
            window = str(current_window + offset).encode()
            expected = hmac.new(self._hmac_key, challenge + window, hashlib.sha256).digest()
            if hmac.compare_digest(expected, response):
                return True
        return False
