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

    @classmethod
    def from_bytes(cls, data: bytes) -> "FileContainer":
        """Deserialize from wire format."""
        if len(data) < 4:
            raise ValueError("Data too short to contain metadata size header")

        meta_size = int.from_bytes(data[:4], "big")
        if len(data) < 4 + meta_size:
            raise ValueError("Data truncated — metadata incomplete")

        meta = json.loads(data[4 : 4 + meta_size].decode("utf-8"))
        content = data[4 + meta_size :]

        container = cls(
            filename=meta["filename"],
            mime_type=meta["mime_type"],
            content=content,
            timestamp=meta.get("timestamp"),
            source_device=meta.get("source_device"),
        )

        # Integrity check
        if container.checksum != meta.get("checksum"):
            raise ValueError(
                f"Integrity check failed for '{meta['filename']}' — "
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
        """Write content to disk, handling duplicate filenames."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        target = out / self.filename

        # Deduplicate
        counter = 1
        while target.exists():
            stem = Path(self.filename).stem
            suffix = Path(self.filename).suffix
            target = out / f"{stem}_{counter}{suffix}"
            counter += 1

        target.write_bytes(self.content)
        return target
