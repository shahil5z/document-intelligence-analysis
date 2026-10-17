"""Pure functions for validating and normalising uploaded files."""

import codecs
import hashlib
import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import BinaryIO

from app.core.errors import InvalidUploadError, PayloadTooLargeError, UnsupportedMediaTypeError

# Content types that are acceptable for each extension. Both lists from configuration
# must allow a value *and* the pair must be consistent with this mapping.
EXTENSION_CONTENT_TYPES: dict[str, frozenset[str]] = {
    "pdf": frozenset({"application/pdf"}),
    "docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    "txt": frozenset({"text/plain"}),
}

MAX_FILENAME_LENGTH = 255
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\- ()]+", re.UNICODE)


def sanitize_filename(raw: str | None) -> str:
    """Return a display-safe base name: no directories, control characters or odd symbols."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFKC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = _UNSAFE_FILENAME_CHARS.sub("_", name).strip(" .")
    name = re.sub(r"_+", "_", name)
    if not name:
        return "unnamed"
    if len(name) > MAX_FILENAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            name = stem[: MAX_FILENAME_LENGTH - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_FILENAME_LENGTH]
    return name


def file_extension(filename: str) -> str:
    _, dot, ext = filename.rpartition(".")
    return ext.lower() if dot else ""


def normalize_content_type(raw: str | None) -> str:
    return (raw or "").split(";", 1)[0].strip().lower()


def validate_file_type(
    *,
    filename: str,
    content_type: str,
    allowed_extensions: list[str],
    allowed_content_types: list[str],
) -> str:
    """Validate extension and declared content type; return the extension."""
    extension = file_extension(filename)
    if extension not in allowed_extensions or extension not in EXTENSION_CONTENT_TYPES:
        raise UnsupportedMediaTypeError(
            f"File extension not allowed. Allowed: {', '.join(sorted(allowed_extensions))}"
        )
    if content_type not in allowed_content_types:
        raise UnsupportedMediaTypeError("Content type not allowed")
    if content_type not in EXTENSION_CONTENT_TYPES[extension]:
        raise UnsupportedMediaTypeError("Content type does not match the file extension")
    return extension


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        # Incremental decoder tolerates a multi-byte character cut at the chunk boundary.
        codecs.getincrementaldecoder("utf-8")().decode(head, final=False)
    except UnicodeDecodeError:
        return False
    return True


_SIGNATURE_CHECKS: dict[str, Callable[[bytes], bool]] = {
    "pdf": lambda head: head.startswith(b"%PDF-"),
    # DOCX is a ZIP container; deeper validation (word/document.xml) is left to extraction.
    "docx": lambda head: head.startswith(b"PK\x03\x04"),
    "txt": _looks_like_text,
}


def check_signature(extension: str, head: bytes) -> None:
    if not _SIGNATURE_CHECKS[extension](head):
        raise UnsupportedMediaTypeError("File content does not match its declared type")


@dataclass
class StreamDigest:
    """Accumulates size and SHA-256 while chunks flow to storage."""

    size: int = 0
    _sha256: "hashlib._Hash" = field(default_factory=hashlib.sha256)

    @property
    def hexdigest(self) -> str:
        return self._sha256.hexdigest()

    def update(self, chunk: bytes) -> None:
        self.size += len(chunk)
        self._sha256.update(chunk)


def validated_chunks(
    stream: BinaryIO,
    *,
    extension: str,
    max_size: int,
    chunk_size: int,
    digest: StreamDigest,
) -> Iterator[bytes]:
    """Yield the stream in chunks, enforcing the size limit and checking magic bytes.

    Raises ``PayloadTooLargeError`` as soon as the running total exceeds ``max_size``,
    so storage aborts without writing the remainder.
    """
    first = True
    while chunk := stream.read(chunk_size):
        if first:
            check_signature(extension, chunk)
            first = False
        digest.update(chunk)
        if digest.size > max_size:
            raise PayloadTooLargeError(
                f"Uploaded file exceeds the maximum allowed size of {max_size} bytes"
            )
        yield chunk
    if first:
        raise InvalidUploadError("Uploaded file is empty")
