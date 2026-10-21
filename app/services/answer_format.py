"""Presentation clean-up of a validated answer.

The model cites sources with ``[n]`` markers. ``AnswerService`` validates them against the
passages that were sent (grounding) and returns the citations as structured data; the
answer text shown to users is then passed through :func:`strip_citation_markers` so it is
plain, presentation-ready Markdown.

Only bare citation markers are removed: ``[1]``, ``[2][3]``, ``[1, 2]`` (after
``normalize_markers`` every accepted style is ``[n]``). Markdown is left alone: numbered
lists (``1.``), links and images (``[text](url)``, ``[1](url)``), reference definitions
(``[1]: url``), reference links (``[text][1]``), and anything inside fenced or inline code.
"""

import re

from app.services.answer_parsing import MAX_SOURCE_NUMBER

_FENCE = re.compile(r"^(\s*)(```|~~~)")
# One run of markers, with the horizontal whitespace before it.
_RUN = re.compile(r"[ \t]*(?<![\]!\\])((?:\[\s*\d{1,3}(?:\s*,\s*\d{1,3})*\s*\])+)(?![(:\[])")
_INLINE_CODE = re.compile(r"(`+)(.+?)\1")


def _is_citation_run(run: str) -> bool:
    return all(0 < int(n) <= MAX_SOURCE_NUMBER for n in re.findall(r"\d+", run))


def _strip_segment(text: str) -> str:
    def _sub(match: re.Match[str]) -> str:
        return "" if _is_citation_run(match.group(1)) else match.group(0)

    out = _RUN.sub(_sub, text)
    # Tidy what a removed marker leaves behind: "word ." -> "word.", double spaces.
    out = re.sub(r"(?<=\S)[ \t]+([.,;:!?)])", r"\1", out)
    out = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", out)
    return out.rstrip(" \t")


def _strip_line(line: str) -> str:
    # Inline code spans are swapped for placeholders so their contents are never touched.
    spans: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        spans.append(match.group(0))
        return f"\x00{len(spans) - 1}\x00"

    cleaned = _strip_segment(_INLINE_CODE.sub(_hold, line))
    return re.sub("\x00(\\d+)\x00", lambda m: spans[int(m.group(1))], cleaned)


def strip_citation_markers(text: str) -> str:
    """Return ``text`` without ``[n]`` citation markers, outside code, with tidy spacing."""
    lines = text.split("\n")
    out: list[str] = []
    fence: str | None = None
    for line in lines:
        match = _FENCE.match(line)
        if fence is not None:
            out.append(line)
            if match and match.group(2) == fence:
                fence = None
            continue
        if match:
            fence = match.group(2)
            out.append(line)
            continue
        out.append(_strip_line(line) if "[" in line else line)
    return "\n".join(out).strip()
