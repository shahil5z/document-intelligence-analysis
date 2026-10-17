from collections.abc import Iterator
from pathlib import Path

import pytest

from app.storage.base import StorageKeyError
from app.storage.local import LocalStorage


def test_save_read_delete_roundtrip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    written = storage.save("documents/u1/file.txt", [b"hello ", b"world"])
    assert written == 11
    assert storage.exists("documents/u1/file.txt")
    assert b"".join(storage.iter_chunks("documents/u1/file.txt", chunk_size=4)) == b"hello world"
    assert storage.delete("documents/u1/file.txt") is True
    assert storage.delete("documents/u1/file.txt") is False
    assert not storage.exists("documents/u1/file.txt")


@pytest.mark.parametrize(
    "key",
    ["../escape.txt", "documents/../../escape", "/etc/passwd", "a//b", "", "a/./b", ".hidden"],
)
def test_path_traversal_and_malformed_keys_are_rejected(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path / "root")
    with pytest.raises(StorageKeyError):
        storage.save(key, [b"x"])


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir()
    storage = LocalStorage(root)
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorageKeyError):
        storage.save("link/file.txt", [b"x"])


def test_failed_stream_leaves_no_file_behind(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)

    def chunks() -> Iterator[bytes]:
        yield b"partial"
        raise RuntimeError("client went away")

    with pytest.raises(RuntimeError):
        storage.save("documents/u1/f.txt", chunks())
    assert not storage.exists("documents/u1/f.txt")
    assert list((tmp_path / "documents" / "u1").iterdir()) == []
