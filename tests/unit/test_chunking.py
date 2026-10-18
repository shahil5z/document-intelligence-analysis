from itertools import pairwise

import pytest

from app.processing.chunking import (
    ApproximateTokenCounter,
    ChunkLimitExceededError,
    RecursiveTokenChunker,
)
from app.processing.content import DocumentContent, PageText

COUNTER = ApproximateTokenCounter()


def _chunker(size: int = 40, overlap: int = 8, max_chunks: int = 1000) -> RecursiveTokenChunker:
    return RecursiveTokenChunker(
        COUNTER, chunk_size=size, chunk_overlap=overlap, max_chunks=max_chunks
    )


def _sentences(count: int, prefix: str = "Sentence") -> str:
    return " ".join(f"{prefix} number {i} talks about topic {i}." for i in range(count))


def test_short_text_is_one_chunk() -> None:
    chunks = _chunker().chunk_text("A short paragraph.")
    assert len(chunks) == 1
    assert chunks[0].text == "A short paragraph."
    assert (chunks[0].char_start, chunks[0].char_end) == (0, 18)
    assert chunks[0].index == 0


def test_chunks_respect_size_and_offsets_are_exact() -> None:
    text = _sentences(60)
    chunks = _chunker(size=40, overlap=8).chunk_text(text)
    assert len(chunks) > 5
    for index, chunk in enumerate(chunks):
        assert chunk.index == index
        assert chunk.token_count <= 40
        assert text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.text == chunk.text.strip()


def test_overlap_repeats_trailing_sentences() -> None:
    text = _sentences(30)
    chunks = _chunker(size=40, overlap=12).chunk_text(text)
    for previous, current in pairwise(chunks):
        assert current.char_start < previous.char_end  # overlapping ranges
    no_overlap = _chunker(size=40, overlap=0).chunk_text(text)
    for previous, current in pairwise(no_overlap):
        assert current.char_start >= previous.char_end


def test_prefers_paragraph_boundaries() -> None:
    paragraphs = ["Alpha " * 15, "Beta " * 15, "Gamma " * 15]
    text = "\n\n".join(p.strip() for p in paragraphs)
    # Each paragraph is ~23 approximate tokens; two never fit in 30.
    chunks = _chunker(size=30, overlap=0).chunk_text(text)
    assert [chunk.text.split()[0] for chunk in chunks] == ["Alpha", "Beta", "Gamma"]
    assert all(len(set(chunk.text.split())) == 1 for chunk in chunks)


def test_hard_split_for_unbroken_text() -> None:
    text = "x" * 1000
    chunks = _chunker(size=50, overlap=0).chunk_text(text)
    assert "".join(chunk.text for chunk in chunks) == text
    assert all(chunk.token_count <= 50 for chunk in chunks)


def test_page_ranges_follow_offsets() -> None:
    content = DocumentContent(
        pages=(
            PageText(1, _sentences(8, "First")),
            PageText(2, ""),
            PageText(3, _sentences(8, "Third")),
        ),
        source_format="pdf",
    )
    chunks = _chunker(size=40, overlap=0).chunk(content)
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 3
    for chunk in chunks:
        assert chunk.page_start is not None
        assert chunk.page_end is not None
        assert chunk.page_start <= chunk.page_end
        if chunk.text.startswith("Third"):
            assert chunk.page_start == 3
    assert any(chunk.page_start == 1 and chunk.page_end == 3 for chunk in chunks) or all(
        chunk.page_start == chunk.page_end for chunk in chunks
    )


def test_unpaginated_content_has_no_pages() -> None:
    content = DocumentContent(pages=(PageText(None, "Plain text"),), source_format="txt")
    chunk = _chunker().chunk(content)[0]
    assert (chunk.page_start, chunk.page_end) == (None, None)


def test_empty_text_gives_no_chunks() -> None:
    assert _chunker().chunk_text("   \n\n ") == []


def test_max_chunk_limit() -> None:
    with pytest.raises(ChunkLimitExceededError) as excinfo:
        _chunker(size=40, overlap=0, max_chunks=3).chunk_text(_sentences(100))
    assert excinfo.value.limit == 3


def test_chunking_is_deterministic() -> None:
    text = _sentences(40)
    assert _chunker().chunk_text(text) == _chunker().chunk_text(text)


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (10, 10), (10, -1)])
def test_invalid_configuration(size: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="chunk"):
        RecursiveTokenChunker(COUNTER, chunk_size=size, chunk_overlap=overlap, max_chunks=10)


def test_approximate_counter() -> None:
    assert COUNTER.count_tokens("") == 0
    assert COUNTER.count_tokens("Hello, world!") == 4
    assert COUNTER.count_tokens("a" * 40) == 10
