from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from app.storage.storage_backend import StorageBackend, get_storage_backend

logger = logging.getLogger(__name__)


# Learner Note: Doc cache service is part of the distributed caching layer.
class DocCacheService:
    # Learner note: Initializes this component so its dependencies and runtime state are explicit.
    """Represent doc cache service within the distributed caching layer.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def __init__(self, backend: StorageBackend | None = None):
        """Initialize init dependencies and runtime state.

        Learner Note:
            Explicit initialization keeps object construction predictable and testable.
        """
        self.backend = backend or get_storage_backend()

    # Learner note: Encapsulates compute content hash so this responsibility can be understood, tested, and changed independently.
    def compute_content_hash(self, content: bytes) -> str:
        """Perform compute content hash for the distributed caching layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return hashlib.sha256(content).hexdigest()

    # Learner note: Encapsulates compute file hash so this responsibility can be understood, tested, and changed independently.
    def compute_file_hash(self, file_path: str | Path, chunk_size: int = 8192) -> str:
        """Perform compute file hash for the distributed caching layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        digest = hashlib.sha256()
        path = Path(file_path)

        with path.open("rb") as file_obj:
            while True:
                chunk = file_obj.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)

        return digest.hexdigest()

    # Learner note: Encapsulates metadata key so this responsibility can be understood, tested, and changed independently.
    def _metadata_key(self, content_hash: str) -> str:
        """Support the distributed caching layer by performing metadata key.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        return f"{content_hash}/metadata.json"

    # Learner note: Encapsulates exists so this responsibility can be understood, tested, and changed independently.
    def exists(self, content_hash: str) -> bool:
        """Perform exists for the distributed caching layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return self.backend.exists(self._metadata_key(content_hash))

    # Learner note: Persists set metadata consistently so state changes remain controlled and testable.
    def set_metadata(self, content_hash: str, metadata: dict[str, Any]) -> bool:
        """Perform set metadata for the distributed caching layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        try:
            payload = json.dumps(metadata).encode("utf-8")
            self.backend.save_bytes(self._metadata_key(content_hash), payload)
            return True
        except Exception:
            logger.exception("Failed to store document metadata hash=%s", content_hash)
            return False

    # Learner note: Retrieves get metadata in one place so callers share consistent access behavior.
    def get_metadata(self, content_hash: str) -> dict[str, Any] | None:
        """Perform get metadata for the distributed caching layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        key = self._metadata_key(content_hash)
        if not self.backend.exists(key):
            return None

        try:
            data = self.backend.read_bytes(key)
            return json.loads(data.decode("utf-8"))
        except Exception:
            logger.exception("Failed to read document metadata hash=%s", content_hash)
            return None
