import pytest

from app.processing.content import DocumentContent, PageText
from app.processing.normalization import normalize_content, normalize_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\r\nb\rc", "a\nb\nc"),
        ("cafe\u0301", "café"),  # NFD -> NFC
        ("too    many \t spaces", "too many spaces"),
        ("line with trailing   \nnext", "line with trailing\nnext"),
        ("para one\n\n\n\n\npara two", "para one\n\npara two"),
        ("soft\u00adhyphen and zero\u200bwidth", "softhyphen and zerowidth"),
        ("non\u00a0breaking", "non breaking"),
        ("control\x07chars\x00here", "controlcharshere"),
        ("exam-\nple of hyphenation", "example of hyphenation"),
        ("Keep-\nCapitalised", "Keep-\nCapitalised"),
        ("   \n  leading and trailing  \n ", "leading and trailing"),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_paragraphs_and_single_newlines_are_preserved() -> None:
    text = "Title\n\nFirst line\nsecond line\n\nNext paragraph"
    assert normalize_text(text) == text


def test_normalize_content_is_per_page_and_idempotent() -> None:
    content = DocumentContent(
        pages=(PageText(1, "  Page\u00a0one  "), PageText(2, "")), source_format="pdf"
    )
    normalized = normalize_content(content)
    assert [page.text for page in normalized.pages] == ["Page one", ""]
    assert [page.number for page in normalized.pages] == [1, 2]
    assert normalize_content(normalized) == normalized
