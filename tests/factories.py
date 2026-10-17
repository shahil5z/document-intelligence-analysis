"""Small helpers that produce real file contents for upload tests."""

PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def text_file(content: str = "hello world") -> tuple[str, bytes, str]:
    return ("notes.txt", content.encode(), "text/plain")


def pdf_file(name: str = "report.pdf", extra: bytes = b"") -> tuple[str, bytes, str]:
    return (name, PDF_BYTES + extra, "application/pdf")
