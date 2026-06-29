from abc import ABC, abstractmethod

from app.config import settings


class StorageBackend(ABC):
    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def save_bytes(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def url_for(self, key: str) -> str:
        raise NotImplementedError


def get_storage_backend() -> StorageBackend:
    backend = settings.storage_backend.strip().lower()

    if backend == "local":
        from app.storage.local_storage import LocalStorage

        return LocalStorage()

    if backend == "s3":
        from app.storage.s3_storage import S3Storage

        return S3Storage()

    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")