from abc import ABC, abstractmethod

from app.config import settings


# Learner Note: Storage backend is part of the storage abstraction layer.
class StorageBackend(ABC):
    """Represent storage backend within the storage abstraction layer.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """

    # Learner note: Encapsulates exists so this responsibility can be understood, tested, and changed independently.
    @abstractmethod
    def exists(self, key: str) -> bool:
        """Perform exists for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        raise NotImplementedError

    # Learner note: Persists save bytes consistently so state changes remain controlled and testable.
    @abstractmethod
    def save_bytes(self, key: str, data: bytes) -> None:
        """Perform save bytes for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        raise NotImplementedError

    # Learner note: Retrieves read bytes in one place so callers share consistent access behavior.
    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        """Perform read bytes for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        raise NotImplementedError

    # Learner note: Encapsulates url for so this responsibility can be understood, tested, and changed independently.
    @abstractmethod
    def url_for(self, key: str) -> str:
        """Perform url for for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        raise NotImplementedError


# Learner note: Retrieves get storage backend in one place so callers share consistent access behavior.
def get_storage_backend() -> StorageBackend:
    """Perform get storage backend for the storage abstraction layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    backend = settings.storage_backend.strip().lower()

    if backend == "local":
        from app.storage.local_storage import LocalStorage

        return LocalStorage()

    if backend == "s3":
        from app.storage.s3_storage import S3Storage

        return S3Storage()

    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")
