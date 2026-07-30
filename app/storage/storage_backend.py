from abc import ABC, abstractmethod

from app.config import settings


class StorageBackend(ABC):
    """Abstract interface for byte-blob storage backends (e.g. local disk, S3).

    Concrete implementations store and retrieve opaque byte content addressed
    by a string `key`, and can produce a URL/path for accessing that content.
    """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return whether an object for `key` exists in the backend."""
        raise NotImplementedError

    @abstractmethod
    def save_bytes(self, key: str, data: bytes) -> None:
        """Store `data` under `key`, overwriting any existing object."""
        raise NotImplementedError

    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        """Return the raw bytes stored under `key`."""
        raise NotImplementedError

    @abstractmethod
    def url_for(self, key: str) -> str:
        """Return a URL or path that locates the object stored under `key`."""
        raise NotImplementedError


def get_storage_backend() -> StorageBackend:
    """Instantiate the storage backend configured via `settings.storage_backend`.

    Supports "local" (`LocalStorage`) and "s3" (`S3Storage`), importing each
    implementation lazily to avoid unnecessary dependencies. Raises
    `ValueError` for any other configured backend name.
    """
    backend = settings.storage_backend.strip().lower()

    if backend == "local":
        from app.storage.local_storage import LocalStorage

        return LocalStorage()

    if backend == "s3":
        from app.storage.s3_storage import S3Storage

        return S3Storage()

    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")
