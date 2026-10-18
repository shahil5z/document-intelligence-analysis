"""Token-aware recursive chunking with page and character-offset metadata.

The text is split recursively on progressively finer boundaries (paragraphs, lines,
sentences, clauses, words, and finally a hard split) until every segment fits in
``chunk_size`` tokens; segments are then merged greedily into chunks of at most
``chunk_size`` tokens. Overlap is added by repeating whole trailing segments of the
previous chunk up to ``chunk_overlap`` tokens, so overlap never cuts a sentence.
"""

import bisect
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.processing.content import DocumentContent, PageSpan


class TokenCounter(Protocol):
    def count_tokens(self, text: str) -> int: ...


class ApproximateTokenCounter:
    """Dependency-free estimate: max(word/punctuation count, characters / 4).

    Used in tests and for LLM context budgets, where the exact tokenizer is unknown.
    Production chunking uses the embedding model's own tokenizer.
    """

    _TOKEN = re.compile(r"\w+|[^\w\s]")

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(len(self._TOKEN.findall(text)), math.ceil(len(text) / 4))


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    token_count: int


class ChunkLimitExceededError(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"more than {limit} chunks")
        self.limit = limit


class Chunker(Protocol):
    def chunk(self, content: DocumentContent) -> list[TextChunk]: ...


# Boundaries from coarse to fine. A split happens *after* each match, so separators stay
# attached to the preceding segment and offsets remain exact.
_BOUNDARIES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\n{2,}"),
    re.compile(r"\n"),
    re.compile(r"(?<=[.!?])[\"')\]]*\s+"),
    re.compile(r"(?<=[;:,])\s+"),
    re.compile(r"\s+"),
)


@dataclass(frozen=True)
class _Segment:
    start: int
    end: int
    tokens: int


class RecursiveTokenChunker:
    def __init__(
        self,
        token_counter: TokenCounter,
        *,
        chunk_size: int,
        chunk_overlap: int,
        max_chunks: int,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")
        self._counter = token_counter
        self._size = chunk_size
        self._overlap = chunk_overlap
        self._max_chunks = max_chunks

    def chunk(self, content: DocumentContent) -> list[TextChunk]:
        text, spans = content.joined()
        return self.chunk_text(text, spans)

    def chunk_text(self, text: str, spans: Sequence[PageSpan] = ()) -> list[TextChunk]:
        if not text.strip():
            return []
        segments = self._split(text, 0, len(text), 0)
        chunks: list[TextChunk] = []
        current: list[_Segment] = []
        current_tokens = 0
        for segment in segments:
            if current and current_tokens + segment.tokens > self._size:
                self._emit(text, current, spans, chunks)
                current, current_tokens = self._overlap_tail(current)
                while current and current_tokens + segment.tokens > self._size:
                    current_tokens -= current.pop(0).tokens
            current.append(segment)
            current_tokens += segment.tokens
        if current:
            self._emit(text, current, spans, chunks)
        return chunks

    def _overlap_tail(self, segments: list[_Segment]) -> tuple[list[_Segment], int]:
        tail: list[_Segment] = []
        tokens = 0
        for segment in reversed(segments):
            if tokens + segment.tokens > self._overlap:
                break
            tail.insert(0, segment)
            tokens += segment.tokens
        return tail, tokens

    def _emit(
        self,
        text: str,
        segments: list[_Segment],
        spans: Sequence[PageSpan],
        chunks: list[TextChunk],
    ) -> None:
        start, end = segments[0].start, segments[-1].end
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start == end:
            return
        if chunks and chunks[-1].char_start == start and chunks[-1].char_end == end:
            return
        if len(chunks) >= self._max_chunks:
            raise ChunkLimitExceededError(self._max_chunks)
        body = text[start:end]
        page_start, page_end = _page_range(spans, start, end)
        chunks.append(
            TextChunk(
                index=len(chunks),
                text=body,
                char_start=start,
                char_end=end,
                page_start=page_start,
                page_end=page_end,
                token_count=self._counter.count_tokens(body),
            )
        )

    def _split(self, text: str, start: int, end: int, level: int) -> list[_Segment]:
        tokens = self._counter.count_tokens(text[start:end])
        if tokens <= self._size:
            return [_Segment(start, end, tokens)] if start < end else []
        if level >= len(_BOUNDARIES):
            return self._hard_split(text, start, end)
        cuts = [m.end() for m in _BOUNDARIES[level].finditer(text, start, end) if m.end() < end]
        if not cuts:
            return self._split(text, start, end, level + 1)
        segments: list[_Segment] = []
        previous = start
        for cut in [*cuts, end]:
            if cut > previous:
                segments.extend(self._split(text, previous, cut, level + 1))
            previous = cut
        return segments

    def _hard_split(self, text: str, start: int, end: int) -> list[_Segment]:
        """Last resort for very long tokens-without-boundaries (e.g. base64 blobs)."""
        segments: list[_Segment] = []
        position = start
        while position < end:
            low, high = position + 1, end
            # Largest prefix that fits in chunk_size tokens (binary search on characters).
            while low < high:
                middle = (low + high + 1) // 2
                if self._counter.count_tokens(text[position:middle]) <= self._size:
                    low = middle
                else:
                    high = middle - 1
            segments.append(_Segment(position, low, self._counter.count_tokens(text[position:low])))
            position = low
        return segments


def _page_range(spans: Sequence[PageSpan], start: int, end: int) -> tuple[int | None, int | None]:
    numbered = [span for span in spans if span.number is not None]
    if not numbered:
        return None, None
    starts = [span.start for span in numbered]
    first = max(bisect.bisect_right(starts, start) - 1, 0)
    last = max(bisect.bisect_right(starts, end - 1) - 1, 0)
    return numbered[first].number, numbered[last].number
