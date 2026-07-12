from __future__ import annotations

from pathlib import Path

from app.storage.storage_backend import StorageBackend


# Learner Note: Local storage is part of the storage abstraction layer.
class LocalStorage(StorageBackend):
    # Learner note: Initializes this component so its dependencies and runtime state are explicit.
    """Represent local storage within the storage abstraction layer.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def __init__(self, base_dir: str = ".cache/storage"):
        """Initialize init dependencies and runtime state.

        Learner Note:
            Explicit initialization keeps object construction predictable and testable.
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # Learner note: Encapsulates path for so this responsibility can be understood, tested, and changed independently.
    def _path_for(self, key: str) -> Path:
        """Support the storage abstraction layer by performing path for.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        safe_key = key.strip().replace("\\", "/")
        return self.base_dir / safe_key

    # Learner note: Encapsulates exists so this responsibility can be understood, tested, and changed independently.
    def exists(self, key: str) -> bool:
        """Perform exists for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return self._path_for(key).exists()

    # Learner note: Persists save bytes consistently so state changes remain controlled and testable.
    def save_bytes(self, key: str, data: bytes) -> None:
        """Perform save bytes for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    # Learner note: Retrieves read bytes in one place so callers share consistent access behavior.
    def read_bytes(self, key: str) -> bytes:
        """Perform read bytes for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return self._path_for(key).read_bytes()

    # Learner note: Encapsulates url for so this responsibility can be understood, tested, and changed independently.
    def url_for(self, key: str) -> str:
        """Perform url for for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return str(self._path_for(key).resolve())
