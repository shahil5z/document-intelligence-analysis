"""Text extraction from PDF, DOCX and TXT into ``DocumentContent``.

Every failure is raised as ``ExtractionError`` carrying a user-safe message; parser
exception details are logged by type only and never stored or returned. OCR is not
implemented: PDFs without a text layer (scans) fail with a clear message.
"""

import io
import logging
import zipfile
from typing import Protocol

from app.processing.content import DocumentContent, PageText

logger = logging.getLogger(__name__)

# pypdf logs recoverable structure problems at WARNING with document details; keep them out.
logging.getLogger("pypdf").setLevel(logging.ERROR)

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT_CONTENT_TYPE = "text/plain"
DOCX_UNREADABLE = "The DOCX file could not be read (corrupt or unsupported)"


class ExtractionError(Exception):
    """Extraction cannot succeed for this file; retrying will not help."""

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


class DocumentExtractor(Protocol):
    source_format: str

    def extract(self, data: bytes) -> DocumentContent: ...


class PdfExtractor:
    """pypdf-based extraction that keeps 1-based page numbers."""

    source_format = "pdf"

    def extract(self, data: bytes) -> DocumentContent:
        from pypdf import PdfReader  # noqa: PLC0415  (keep parser imports off the API path)
        from pypdf.errors import PdfReadError  # noqa: PLC0415

        if not data:
            raise ExtractionError("The file is empty")
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                # Some PDFs are "encrypted" with an empty user password; anything else is
                # password-protected and cannot be processed.
                try:
                    if not reader.decrypt(""):
                        raise ExtractionError("The PDF is password-protected")
                except ExtractionError:
                    raise
                except Exception as exc:
                    raise ExtractionError("The PDF is password-protected") from exc
            page_objects = list(reader.pages)
        except ExtractionError:
            raise
        except (PdfReadError, ValueError, KeyError, TypeError, OSError, RecursionError) as exc:
            logger.info("extraction.pdf_unreadable", extra={"error_type": type(exc).__name__})
            raise ExtractionError("The PDF could not be read (corrupt or unsupported)") from exc

        pages: list[PageText] = []
        failed_pages = 0
        for number, page in enumerate(page_objects, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                failed_pages += 1
                logger.info(
                    "extraction.pdf_page_failed",
                    extra={"page": number, "error_type": type(exc).__name__},
                )
                text = ""
            pages.append(PageText(number=number, text=text))
        warnings = (f"{failed_pages} page(s) could not be read",) if failed_pages else ()
        return DocumentContent(
            pages=tuple(pages),
            source_format=self.source_format,
            page_count=len(page_objects),
            warnings=warnings,
        )


class DocxExtractor:
    """python-docx extraction of paragraphs and tables in document order."""

    source_format = "docx"

    def __init__(self, max_uncompressed_bytes: int = 100 * 1024 * 1024) -> None:
        self._max_uncompressed_bytes = max_uncompressed_bytes

    def extract(self, data: bytes) -> DocumentContent:
        if not data:
            raise ExtractionError("The file is empty")
        self._check_archive(data)

        import docx  # noqa: PLC0415
        from docx.opc.exceptions import PackageNotFoundError  # noqa: PLC0415
        from docx.table import Table  # noqa: PLC0415

        try:
            document = docx.Document(io.BytesIO(data))
            blocks: list[str] = []
            for item in document.iter_inner_content():
                if isinstance(item, Table):
                    for row in item.rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        # Merged cells repeat their text; drop consecutive duplicates.
                        deduped = [
                            c for i, c in enumerate(cells) if c and (i == 0 or c != cells[i - 1])
                        ]
                        if deduped:
                            blocks.append(" | ".join(deduped))
                else:
                    text = item.text.strip()
                    if text:
                        blocks.append(text)
        except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError, Exception) as exc:
            logger.info("extraction.docx_unreadable", extra={"error_type": type(exc).__name__})
            raise ExtractionError(DOCX_UNREADABLE) from exc
        # DOCX has no stable page model (pagination happens at render time).
        return DocumentContent(
            pages=(PageText(number=None, text="\n\n".join(blocks)),),
            source_format=self.source_format,
        )

    def _check_archive(self, data: bytes) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                total = sum(info.file_size for info in archive.infolist())
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            raise ExtractionError(DOCX_UNREADABLE) from exc
        if total > self._max_uncompressed_bytes:
            raise ExtractionError("The DOCX file expands to more data than allowed")


class TextExtractor:
    """Plain text with BOM detection, strict UTF-8, then a cp1252 fallback."""

    source_format = "txt"

    def extract(self, data: bytes) -> DocumentContent:
        if not data:
            raise ExtractionError("The file is empty")
        text, encoding = decode_text(data)
        warnings = (f"decoded as {encoding}",) if encoding == "cp1252" else ()
        return DocumentContent(
            pages=(PageText(number=None, text=text),),
            source_format=self.source_format,
            warnings=warnings,
        )


_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


def decode_text(data: bytes) -> tuple[str, str]:
    """Return ``(text, encoding)``. Raises ``ExtractionError`` for binary content."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError as exc:
                raise ExtractionError("The text file could not be decoded") from exc
    if b"\x00" in data:
        raise ExtractionError("The file does not look like text")
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        # cp1252 maps almost every byte; the five undefined bytes become U+FFFD.
        return data.decode("cp1252", errors="replace"), "cp1252"


class ExtractorRegistry:
    def __init__(self, extractors: dict[str, DocumentExtractor]) -> None:
        self._extractors = dict(extractors)

    def for_content_type(self, content_type: str) -> DocumentExtractor:
        extractor = self._extractors.get(content_type.lower())
        if extractor is None:
            raise ExtractionError("This file type is not supported for text extraction")
        return extractor


def default_registry(max_docx_uncompressed_bytes: int = 100 * 1024 * 1024) -> ExtractorRegistry:
    return ExtractorRegistry(
        {
            PDF_CONTENT_TYPE: PdfExtractor(),
            DOCX_CONTENT_TYPE: DocxExtractor(max_docx_uncompressed_bytes),
            TXT_CONTENT_TYPE: TextExtractor(),
        }
    )
