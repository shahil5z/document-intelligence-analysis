import io

import pytest

from app.core.errors import InvalidUploadError, PayloadTooLargeError, UnsupportedMediaTypeError
from app.services.upload_validation import (
    StreamDigest,
    check_signature,
    normalize_content_type,
    sanitize_filename,
    validate_file_type,
    validated_chunks,
)

ALLOWED_EXT = ["pdf", "docx", "txt"]
ALLOWED_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\report.pdf", "report.pdf"),
        ("my<script>.pdf", "my_script_.pdf"),
        ("bad\x00name\x1f.txt", "badname.txt"),
        ("...", "unnamed"),
        (None, "unnamed"),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates_but_keeps_extension() -> None:
    name = sanitize_filename("a" * 400 + ".pdf")
    assert len(name) == 255
    assert name.endswith(".pdf")


def test_content_type_parameters_are_stripped() -> None:
    assert normalize_content_type("Text/Plain; charset=utf-8") == "text/plain"


def test_valid_type_combination_returns_extension() -> None:
    ext = validate_file_type(
        filename="a.PDF",
        content_type="application/pdf",
        allowed_extensions=ALLOWED_EXT,
        allowed_content_types=ALLOWED_TYPES,
    )
    assert ext == "pdf"


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("malware.exe", "application/pdf"),
        ("report.pdf", "application/zip"),
        ("report.pdf", "text/plain"),
        ("noextension", "text/plain"),
    ],
)
def test_invalid_type_combinations_are_rejected(filename: str, content_type: str) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        validate_file_type(
            filename=filename,
            content_type=content_type,
            allowed_extensions=ALLOWED_EXT,
            allowed_content_types=ALLOWED_TYPES,
        )


def test_signature_checks() -> None:
    check_signature("pdf", b"%PDF-1.7 ...")
    check_signature("docx", b"PK\x03\x04rest")
    check_signature("txt", "plain text äöü".encode())
    for ext, head in [("pdf", b"not a pdf"), ("docx", b"%PDF-"), ("txt", b"\x00\x01binary")]:
        with pytest.raises(UnsupportedMediaTypeError):
            check_signature(ext, head)


def test_validated_chunks_enforces_limit_while_streaming() -> None:
    digest = StreamDigest()
    chunks = validated_chunks(
        io.BytesIO(b"x" * 100), extension="txt", max_size=50, chunk_size=10, digest=digest
    )
    with pytest.raises(PayloadTooLargeError):
        list(chunks)
    assert digest.size == 60  # stopped on the first chunk past the limit


def test_validated_chunks_rejects_empty_stream() -> None:
    with pytest.raises(InvalidUploadError):
        list(
            validated_chunks(
                io.BytesIO(b""), extension="txt", max_size=50, chunk_size=10, digest=StreamDigest()
            )
        )
