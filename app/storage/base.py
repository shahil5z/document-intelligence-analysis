"""Storage abstraction. Callers deal in opaque keys, never filesystem paths or URLs."""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator


class StorageError(Exception):
    """Raised when the storage backend cannot complete an operation."""


class StorageKeyError(StorageError):
    """Raised for keys that are malformed or would escape the storage root."""


class StorageService(ABC):
    @abstractmethod
    def save(self, key: str, chunks: Iterable[bytes]) -> int:
        """Persist ``chunks`` under ``key`` atomically and return the number of bytes written.

        If iterating ``chunks`` raises, nothing is left behind under ``key`` and the
        original exception propagates (used to abort oversized uploads mid-stream).
        """

    @abstractmethod
    def iter_chunks(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        """Yield the stored bytes in chunks. Raises ``FileNotFoundError`` if missing."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete the object; return ``False`` if it did not exist."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...
