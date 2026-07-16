"""
File containerization — serialize/deserialize files with metadata.

Wire format:
    [4 bytes: metadata_size (big-endian uint32)]
    [metadata_size bytes: JSON metadata (UTF-8)]
    [remaining bytes: raw file content]

Metadata includes filename, MIME type, timestamp, source device, SHA-256 checksum.
"""

import hashlib
import json
import mimetypes
import socket
from datetime import datetime, timezone
from pathlib import Path


class FileContainer:
    """Immutable wrapper around a file's content + metadata."""

    def __init__(
        self,
        filename: str,
        mime_type: str,
        content: bytes,
        timestamp: str | None = None,
        source_device: str | None = None,
    ):
        self.filename = filename
        self.mime_type = mime_type
        self.content = content
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self.source_device = source_device or socket.gethostname()
        self.checksum = self._sha256(self.content)

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def verify_integrity(self) -> bool:
        return self.checksum == self._sha256(self.content)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialize to wire format."""
        metadata = {
            "filename": self.filename,
            "mime_type": self.mime_type,
            "timestamp": self.timestamp,
            "source_device": self.source_device,
            "checksum": self.checksum,
            "content_size": len(self.content),
        }
        meta_bytes = json.dumps(metadata).encode("utf-8")
        return len(meta_bytes).to_bytes(4, "big") + meta_bytes + self.content

    # Maximum metadata JSON size (64 KB should be more than enough)
    _MAX_METADATA_SIZE = 65536

    @classmethod
    def from_bytes(cls, data: bytes) -> "FileContainer":
        """Deserialize from wire format.

        Security: validates metadata size bounds, required fields, and sanitizes filename.
        """
        if len(data) < 4:
            raise ValueError("Data too short to contain metadata size header")

        meta_size = int.from_bytes(data[:4], "big")

        # Guard against absurd metadata sizes (DoS / malformed data)
        if meta_size > cls._MAX_METADATA_SIZE:
            raise ValueError(f"Metadata size {meta_size} exceeds maximum ({cls._MAX_METADATA_SIZE})")

        if len(data) < 4 + meta_size:
            raise ValueError("Data truncated — metadata incomplete")

        try:
            meta = json.loads(data[4 : 4 + meta_size].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid metadata JSON: {e}")

        # Validate required fields exist and have expected types
        if not isinstance(meta.get("filename"), str) or not meta["filename"]:
            raise ValueError("Missing or invalid 'filename' in metadata")
        if not isinstance(meta.get("mime_type"), str):
            raise ValueError("Missing or invalid 'mime_type' in metadata")

        # Reject filenames with null bytes (potential exploit)
        raw_filename = meta["filename"]
        if "\x00" in raw_filename:
            raise ValueError("Filename contains null bytes")

        # Reject excessively long filenames
        if len(raw_filename) > 512:
            raise ValueError(f"Filename too long ({len(raw_filename)} chars, max 512)")

        # Sanitize filename immediately at deserialization (defense in depth)
        safe_filename = cls._sanitize_filename(raw_filename)

        content = data[4 + meta_size :]

        container = cls(
            filename=safe_filename,
            mime_type=meta["mime_type"],
            content=content,
            timestamp=meta.get("timestamp"),
            source_device=meta.get("source_device"),
        )

        # Integrity check
        if container.checksum != meta.get("checksum"):
            raise ValueError(
                f"Integrity check failed for '{safe_filename}' — "
                f"expected {meta.get('checksum')}, got {container.checksum}"
            )

        return container

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def create_from_file(cls, file_path: str | Path) -> "FileContainer":
        """Create container from a file on disk."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(path))

        return cls(
            filename=path.name,
            mime_type=mime_type or "application/octet-stream",
            content=content,
        )

    @classmethod
    def create_from_text(cls, text: str, filename: str | None = None) -> "FileContainer":
        """Create container from a text snippet."""
        if not filename:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"snippet_{ts}.txt"

        return cls(
            filename=filename,
            mime_type="text/plain",
            content=text.encode("utf-8"),
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def save_to_file(self, output_dir: str | Path) -> Path:
        """Write content to disk, handling duplicate filenames.

        Security: sanitizes filename to prevent path traversal attacks.
        """
        out = Path(output_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)

        # Sanitize filename: strip path separators, null bytes, and resolve to basename only
        safe_name = self._sanitize_filename(self.filename)
        target = out / safe_name

        # Verify the resolved path is still within output_dir (defense in depth)
        if not target.resolve().is_relative_to(out):
            raise ValueError(f"Path traversal detected in filename: {self.filename!r}")

        # Deduplicate
        counter = 1
        while target.exists():
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix
            target = out / f"{stem}_{counter}{suffix}"
            counter += 1

        target.write_bytes(self.content)
        return target

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitize a filename to prevent path traversal and invalid characters.

        Strips directory components, null bytes, and control characters.
        Falls back to a safe default if nothing remains.
        """
        # Remove null bytes and control characters
        cleaned = filename.replace("\x00", "").strip()

        # Take only the basename (strip any directory traversal)
        cleaned = Path(cleaned).name

        # Remove leading dots (hidden files / traversal fragments)
        cleaned = cleaned.lstrip(".")

        # Replace remaining problematic characters
        for char in ("/", "\\", "\x00"):
            cleaned = cleaned.replace(char, "_")

        # Fallback if empty after sanitization
        if not cleaned:
            cleaned = "unnamed_file"

        # Limit filename length (255 bytes is typical filesystem max)
        if len(cleaned.encode("utf-8")) > 240:
            stem = Path(cleaned).stem[:200]
            suffix = Path(cleaned).suffix[:40]
            cleaned = stem + suffix

        return cleaned
