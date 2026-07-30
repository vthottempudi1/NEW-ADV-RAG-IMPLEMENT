from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from app.storage.storage_backend import StorageBackend, get_storage_backend

logger = logging.getLogger(__name__)


class DocCacheService:
    """Content-addressed cache for document metadata, keyed by a SHA-256 hash of document bytes.

    Stores/retrieves a JSON metadata blob per content hash through a pluggable
    StorageBackend (e.g. local disk or S3), so repeated ingestion of identical
    document content can skip reprocessing.
    """

    def __init__(self, backend: StorageBackend | None = None):
        """Use the given StorageBackend, or fall back to the process-wide default backend."""
        self.backend = backend or get_storage_backend()

    def compute_content_hash(self, content: bytes) -> str:
        """Return the hex SHA-256 digest of `content`, used as the cache key."""
        return hashlib.sha256(content).hexdigest()

    def compute_file_hash(self, file_path: str | Path, chunk_size: int = 8192) -> str:
        """Return the hex SHA-256 digest of a file's contents, reading it in `chunk_size`-byte chunks to bound memory use."""
        digest = hashlib.sha256()
        path = Path(file_path)

        with path.open("rb") as file_obj:
            while True:
                chunk = file_obj.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)

        return digest.hexdigest()

    def _metadata_key(self, content_hash: str) -> str:
        """Return the storage backend key under which metadata for `content_hash` is stored."""
        return f"{content_hash}/metadata.json"

    def exists(self, content_hash: str) -> bool:
        """Return True if metadata has already been cached for this content hash."""
        return self.backend.exists(self._metadata_key(content_hash))

    def set_metadata(self, content_hash: str, metadata: dict[str, Any]) -> bool:
        """Serialize `metadata` to JSON and store it for `content_hash`. Returns True on success, False (logging the exception) on failure."""
        try:
            payload = json.dumps(metadata).encode("utf-8")
            self.backend.save_bytes(self._metadata_key(content_hash), payload)
            return True
        except Exception:
            logger.exception("Failed to store document metadata hash=%s", content_hash)
            return False

    def get_metadata(self, content_hash: str) -> dict[str, Any] | None:
        """Return the cached metadata dict for `content_hash`, or None if not cached or if reading/parsing fails."""
        key = self._metadata_key(content_hash)
        if not self.backend.exists(key):
            return None

        try:
            data = self.backend.read_bytes(key)
            return json.loads(data.decode("utf-8"))
        except Exception:
            logger.exception("Failed to read document metadata hash=%s", content_hash)
            return None
