"""Structured representation of extracted document text."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PageText:
    """Text of one page. ``number`` is 1-based for paginated formats, ``None`` otherwise."""

    number: int | None
    text: str


@dataclass(frozen=True)
class PageSpan:
    """Character range ``[start, end)`` of one page inside ``DocumentContent.full_text``."""

    number: int | None
    start: int
    end: int


PAGE_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class DocumentContent:
    pages: tuple[PageText, ...]
    source_format: str
    page_count: int | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_text(self) -> bool:
        return any(page.text.strip() for page in self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(page.text) for page in self.pages)

    def joined(self) -> tuple[str, tuple[PageSpan, ...]]:
        """Concatenate non-empty pages with blank lines and record each page's span.

        Chunk character offsets refer to this joined, normalized text (not file bytes).
        """
        parts: list[str] = []
        spans: list[PageSpan] = []
        position = 0
        for page in self.pages:
            if not page.text:
                continue
            if parts:
                parts.append(PAGE_SEPARATOR)
                position += len(PAGE_SEPARATOR)
            parts.append(page.text)
            spans.append(PageSpan(page.number, position, position + len(page.text)))
            position += len(page.text)
        return "".join(parts), tuple(spans)
