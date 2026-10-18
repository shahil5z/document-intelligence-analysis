"""Local filesystem storage with a path-traversal guard."""

import os
import re
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from app.storage.base import StorageKeyError, StorageService

KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


class LocalStorage(StorageService):
    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # Two independent guards: a strict key grammar, and a resolved-path containment check
        # (which also defeats symlinks pointing outside the root).
        if not KEY_PATTERN.fullmatch(key) or ".." in key.split("/"):
            raise StorageKeyError("Invalid storage key")
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root) or path == self._root:
            raise StorageKeyError("Storage key escapes the storage root")
        return path

    def save(self, key: str, chunks: Iterable[bytes]) -> int:
        target = self._path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".upload-", suffix=".part")
        written = 0
        try:
            with os.fdopen(fd, "wb") as handle:
                for chunk in chunks:
                    handle.write(chunk)
                    written += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return written

    def iter_chunks(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        path = self._path_for(key)
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    def delete(self, key: str) -> bool:
        path = self._path_for(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()
