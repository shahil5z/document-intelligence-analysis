"""Prompt construction for grounded question answering.

The prompt text lives in ``app/prompt/`` (system rules, output contract). This module
only assembles the messages:

* system message: ``app/prompt/system.md``, never mixed with user or document text;
* user message: the question in ``<question>``, the retrieved excerpts inside
  ``<untrusted_sources>``, each in ``<source id="1" ...>``, then
  ``app/prompt/answer_instructions.md``.

Angle brackets inside excerpts and the question are escaped so document text cannot close
the wrapper tags or impersonate other sources.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.ai.base import ChatMessage
from app.processing.chunking import TokenCounter
from app.prompt import answer_instructions, system_prompt
from app.services.answer_parsing import INSUFFICIENT_EVIDENCE_SENTINEL
from app.services.retrieval import RankedChunk

__all__ = [
    "INSUFFICIENT_EVIDENCE_SENTINEL",
    "ContextSource",
    "build_context",
    "build_messages",
]


@dataclass(frozen=True)
class ContextSource:
    """A passage sent to the model as source ``number`` (API label ``S<number>``)."""

    number: int
    item: RankedChunk

    @property
    def label(self) -> str:
        return f"S{self.number}"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pages(item: RankedChunk) -> str:
    hit = item.hit
    if hit.page_start is None:
        return "n/a"
    if hit.page_end is None or hit.page_end == hit.page_start:
        return str(hit.page_start)
    return f"{hit.page_start}-{hit.page_end}"


def _render_source(number: int, item: RankedChunk, body: str) -> str:
    filename = _escape(item.hit.filename).replace('"', "&quot;")
    return (
        f'<source id="{number}" document="{filename}" pages="{_pages(item)}">\n'
        f"{_escape(body)}\n</source>"
    )


def build_context(
    ranked: Sequence[RankedChunk], *, max_tokens: int, counter: TokenCounter
) -> list[ContextSource]:
    """Select sources in rank order within ``max_tokens``.

    Duplicates are dropped: identical text, or a chunk whose character range lies inside
    an already selected chunk of the same document (overlap from chunking).
    """
    selected: list[ContextSource] = []
    seen_text: set[str] = set()
    ranges: dict[uuid.UUID, list[tuple[int, int]]] = {}
    used = 0
    for candidate in ranked:
        item = candidate
        hit = item.hit
        key = " ".join(hit.content.split()).lower()
        if key in seen_text:
            continue
        if any(
            start <= hit.char_start and hit.char_end <= end
            for start, end in ranges.get(hit.document_id, [])
        ):
            continue
        number = len(selected) + 1
        cost = counter.count_tokens(_render_source(number, item, hit.content))
        if used + cost > max_tokens:
            if selected:
                continue
            # Always keep the best source, truncated to the budget.
            ratio = max_tokens / max(cost, 1)
            truncated = hit.content[: max(1, int(len(hit.content) * ratio * 0.9))]
            item = replace(item, hit=replace(hit, content=truncated))
            cost = counter.count_tokens(_render_source(number, item, truncated))
        selected.append(ContextSource(number=number, item=item))
        seen_text.add(key)
        ranges.setdefault(hit.document_id, []).append((hit.char_start, hit.char_end))
        used += cost
    return selected


def build_messages(question: str, sources: Sequence[ContextSource]) -> list[ChatMessage]:
    rendered = "\n".join(
        _render_source(source.number, source.item, source.item.hit.content) for source in sources
    )
    user = (
        f"<question>\n{_escape(question)}\n</question>\n\n"
        "<untrusted_sources>\n"
        f"{rendered}\n"
        "</untrusted_sources>\n\n"
        f"{answer_instructions(len(sources))}"
    )
    return [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user},
    ]
