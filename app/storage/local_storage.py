from __future__ import annotations

from pathlib import Path

from app.storage.storage_backend import StorageBackend


class LocalStorage(StorageBackend):
    def __init__(self, base_dir: str = ".cache/storage"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        safe_key = key.strip().replace("\\", "/")
        return self.base_dir / safe_key

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()

    def save_bytes(self, key: str, data: bytes) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read_bytes(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()

    def url_for(self, key: str) -> str:
        return str(self._path_for(key).resolve())