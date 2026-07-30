from __future__ import annotations

from pathlib import Path

from app.storage.storage_backend import StorageBackend


class LocalStorage(StorageBackend):
    """Storage backend that persists blobs as files on the local filesystem.

    Keys are treated as relative paths under `base_dir`; useful for local
    development and testing without depending on external object storage.
    """

    def __init__(self, base_dir: str = ".cache/storage"):
        """Set `base_dir` as the storage root, creating it (and parents) if needed."""
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        """Resolve a storage `key` to an absolute filesystem path under `base_dir`.

        Normalizes backslashes to forward slashes so keys behave consistently
        across platforms.
        """
        safe_key = key.strip().replace("\\", "/")
        return self.base_dir / safe_key

    def exists(self, key: str) -> bool:
        """Return whether a file for `key` exists on disk."""
        return self._path_for(key).exists()

    def save_bytes(self, key: str, data: bytes) -> None:
        """Write `data` to the file for `key`, creating parent directories as needed."""
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read_bytes(self, key: str) -> bytes:
        """Read and return the full contents of the file for `key`."""
        return self._path_for(key).read_bytes()

    def url_for(self, key: str) -> str:
        """Return the resolved absolute filesystem path for `key` as a string."""
        return str(self._path_for(key).resolve())
