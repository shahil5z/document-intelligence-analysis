"""Extraction from synthetic PDF, DOCX and TXT fixtures, including failure modes."""

import pytest

from app.processing.extraction import (
    DOCX_CONTENT_TYPE,
    PDF_CONTENT_TYPE,
    TXT_CONTENT_TYPE,
    DocxExtractor,
    ExtractionError,
    PdfExtractor,
    TextExtractor,
    decode_text,
    default_registry,
)
from tests.fixtures.builders import build_docx, build_encrypted_pdf, build_pdf


def test_pdf_keeps_page_numbers_and_text() -> None:
    data = build_pdf([["Alpha page one."], [], ["Gamma page three (final)."]])
    content = PdfExtractor().extract(data)
    assert content.page_count == 3
    assert [page.number for page in content.pages] == [1, 2, 3]
    assert "Alpha page one." in content.pages[0].text
    assert content.pages[1].text.strip() == ""
    assert "Gamma page three (final)." in content.pages[2].text
    text, spans = content.joined()
    assert [span.number for span in spans] == [1, 3]
    assert text[spans[1].start : spans[1].end] == content.pages[2].text


def test_pdf_without_text_layer_has_no_text() -> None:
    content = PdfExtractor().extract(build_pdf([[], []]))
    assert content.page_count == 2
    assert not content.has_text


@pytest.mark.parametrize(
    "data",
    [b"%PDF-1.4\nthis is not really a pdf", b"%PDF-1.7\n" + bytes(range(256)) * 4],
)
def test_corrupt_pdf_raises_safe_error(data: bytes) -> None:
    with pytest.raises(ExtractionError) as excinfo:
        PdfExtractor().extract(data)
    assert excinfo.value.safe_message == "The PDF could not be read (corrupt or unsupported)"


def test_encrypted_pdf_is_rejected() -> None:
    with pytest.raises(ExtractionError, match="password-protected"):
        PdfExtractor().extract(build_encrypted_pdf("top secret"))


@pytest.mark.parametrize("extractor", [PdfExtractor(), DocxExtractor(), TextExtractor()])
def test_empty_file_is_rejected(extractor: PdfExtractor | DocxExtractor | TextExtractor) -> None:
    with pytest.raises(ExtractionError, match="empty"):
        extractor.extract(b"")


def test_docx_paragraphs_and_tables_in_order() -> None:
    data = build_docx(
        ["Quarterly Report", "Revenue grew in the third quarter.", "Costs were flat."],
        table=[["Region", "Revenue"], ["EMEA", "120"]],
    )
    content = DocxExtractor().extract(data)
    assert len(content.pages) == 1
    assert content.pages[0].number is None
    text = content.pages[0].text
    assert text.index("Quarterly Report") < text.index("Revenue grew") < text.index("EMEA | 120")
    assert "Region | Revenue" in text


def test_corrupt_docx_raises_safe_error() -> None:
    with pytest.raises(ExtractionError, match="DOCX file could not be read"):
        DocxExtractor().extract(b"PK\x03\x04 definitely not a zip archive")


def test_docx_zip_bomb_guard() -> None:
    data = build_docx(["Title", "x" * 5000])
    with pytest.raises(ExtractionError, match="expands to more data"):
        DocxExtractor(max_uncompressed_bytes=1024).extract(data)


@pytest.mark.parametrize(
    ("data", "expected", "encoding"),
    [
        ("café naïve".encode(), "café naïve", "utf-8"),
        (b"\xef\xbb\xbfbom text", "bom text", "utf-8-sig"),
        ("utf16 text".encode("utf-16"), "utf16 text", "utf-16"),
        ("café".encode("cp1252"), "café", "cp1252"),
    ],
)
def test_text_decoding(data: bytes, expected: str, encoding: str) -> None:
    assert decode_text(data) == (expected, encoding)


def test_binary_content_in_txt_is_rejected() -> None:
    with pytest.raises(ExtractionError, match="does not look like text"):
        TextExtractor().extract(b"MZ\x00\x00\x00binary")


def test_registry_rejects_unsupported_type() -> None:
    registry = default_registry()
    assert isinstance(registry.for_content_type(PDF_CONTENT_TYPE), PdfExtractor)
    assert isinstance(registry.for_content_type(DOCX_CONTENT_TYPE), DocxExtractor)
    assert isinstance(registry.for_content_type(TXT_CONTENT_TYPE), TextExtractor)
    with pytest.raises(ExtractionError, match="not supported"):
        registry.for_content_type("image/png")
