"""Tolerant parsing of the language model's reply for ``POST /ask``.

The model is asked for JSON (``app/prompt/response_schema.json``), sent as an OpenAI
structured-output schema where supported. Real replies still vary, so this module
accepts, in order:

1. a JSON object, bare or inside a Markdown code fence, possibly surrounded by prose,
   with common alternative field names (``answer``/``response``/``text``,
   ``status``/``outcome``, ``citations``/``sources``/``source_ids``) and citation values
   as numbers or strings such as ``"1"``, ``"[2]"``, ``"S3"``, ``"Source 4"``;
2. plain text (no usable JSON) with citation markers.

Citation markers are normalised to ``[n]``. Accepted forms: ``[1]``, ``[1, 2]``,
``[1][2]``, ``[1-3]``, ``[S1]``, ``[Source 1]``, ``[source: 2]``, ``【1】``, ``(Source 1)``
and ``[^1]``. Numbers that do not refer to a sent source are dropped (and counted) by
``validate_citations``. Nothing here logs content.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

ModelStatus = Literal["answered", "partial", "insufficient"]
ParseMode = Literal["json", "fenced_json", "embedded_json", "text", "empty"]

INSUFFICIENT_EVIDENCE_SENTINEL = "INSUFFICIENT_EVIDENCE"
# Never more sources than this are sent (MAX_TOP_K <= 100); bigger bracketed numbers are
# left untouched as ordinary text.
MAX_SOURCE_NUMBER = 100

_FENCE = re.compile(r"```(?:json|JSON)?\s*(\{.*?\})\s*```", re.DOTALL)
_NUMBER_LIST = r"\d+(?:\s*(?:[,;]|-|\u2013|and)\s*(?:S|Source\s*)?\d+)*"
_PREFIX = r"(?:\^|S|Source|source|Src|src|Ref|ref|Doc|doc)?\s*:?\s*#?\s*"
# [1] [1, 2] [S1] [Source 1] [source: 2] [^1] [1-3]   and full-width 【1】
_MARKER = re.compile(r"[\[【]\s*" + _PREFIX + r"(" + _NUMBER_LIST + r")\s*[\]】]")
# (Source 1) / (Sources 1, 2) only with an explicit word, so "(1)" in prose stays as is
_PAREN_MARKER = re.compile(r"\(\s*(?:Sources?|sources?)\s*:?\s*(" + _NUMBER_LIST + r")\s*\)")
_STATUS_ALIASES: dict[str, ModelStatus] = {
    "answered": "answered",
    "answer": "answered",
    "ok": "answered",
    "complete": "answered",
    "supported": "answered",
    "partial": "partial",
    "partially_answered": "partial",
    "insufficient": "insufficient",
    "insufficient_evidence": "insufficient",
    "not_found": "insufficient",
    "unanswerable": "insufficient",
    "no_answer": "insufficient",
}


@dataclass(frozen=True)
class ParsedReply:
    status: ModelStatus
    answer: str
    declared_citations: tuple[int, ...]
    missing_information: str
    mode: ParseMode


def _expand(group: str) -> list[int]:
    numbers: list[int] = []
    for raw_part in re.split(r"\s*(?:[,;]|and)\s*", group):
        part = re.sub(r"(?:S|Source\s*)", "", raw_part.strip())
        if not part:
            continue
        span = re.split(r"\s*[-\u2013]\s*", part)
        if len(span) == 2 and span[0].isdigit() and span[1].isdigit():
            low, high = int(span[0]), int(span[1])
            if 0 < low <= high and high - low <= 20:
                numbers.extend(range(low, high + 1))
                continue
        numbers.extend(int(digits) for digits in re.findall(r"\d+", part))
    return numbers


def normalize_markers(text: str) -> str:
    """Rewrite every recognised citation marker as ``[n]`` (one bracket per number)."""

    def _sub(match: re.Match[str]) -> str:
        numbers = _expand(match.group(1))
        if not numbers or max(numbers) > MAX_SOURCE_NUMBER:
            return match.group(0)  # e.g. a year in brackets, not a citation
        return "".join(f"[{n}]" for n in numbers)

    return _PAREN_MARKER.sub(_sub, _MARKER.sub(_sub, text))


def markers_in(text: str) -> list[int]:
    """Citation numbers in order of first appearance (``text`` already normalised)."""
    seen: list[int] = []
    for digits in re.findall(r"\[(\d+)\]", text):
        number = int(digits)
        if number not in seen:
            seen.append(number)
    return seen


def _as_status(value: Any) -> ModelStatus | None:
    if not isinstance(value, str):
        return None
    return _STATUS_ALIASES.get(value.strip().lower().replace(" ", "_").replace("-", "_"))


def _as_citations(value: Any) -> tuple[int, ...]:
    items = value if isinstance(value, list) else [value] if value is not None else []
    numbers: list[int] = []
    for item in items:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            numbers.append(item)
        elif isinstance(item, str):
            numbers.extend(_expand(re.sub(r"[\[\]【】^#:]|Source|source", " ", item)))
        elif isinstance(item, dict):
            for key in ("id", "source", "source_id", "number", "index"):
                if key in item:
                    numbers.extend(_as_citations(item[key]))
                    break
    return tuple(dict.fromkeys(n for n in numbers if n > 0))


def _first_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            return value
    return None


def _from_object(data: dict[str, Any], mode: ParseMode) -> ParsedReply | None:
    answer = _first_str(data, "answer", "response", "text", "content", "final_answer")
    status = _as_status(data.get("status", data.get("outcome", data.get("result"))))
    if answer is None and status is None:
        return None
    answer = normalize_markers((answer or "").strip())
    if status is None:
        status = "insufficient" if answer.strip() == INSUFFICIENT_EVIDENCE_SENTINEL else "answered"
    citations = _as_citations(
        data.get("citations", data.get("sources", data.get("source_ids", data.get("refs"))))
    )
    missing = _first_str(data, "missing_information", "missing", "gaps", "limitations") or ""
    return ParsedReply(status, answer, citations, missing.strip(), mode)


def _json_objects(raw: str) -> list[tuple[str, ParseMode]]:
    stripped = raw.strip()
    candidates: list[tuple[str, ParseMode]] = []
    if stripped.startswith("{"):
        candidates.append((stripped, "json"))
    candidates += [(match.group(1), "fenced_json") for match in _FENCE.finditer(raw)]
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        candidates.append((raw[start : end + 1], "embedded_json"))
    return candidates


def parse_reply(raw: str) -> ParsedReply:
    """Turn the raw model reply into a ``ParsedReply``. Never raises."""
    if not raw or not raw.strip():
        return ParsedReply("insufficient", "", (), "", "empty")
    for candidate, mode in _json_objects(raw):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            parsed = _from_object(data, mode)
            if parsed is not None:
                return parsed
    text = raw.strip()
    upper = text.upper()
    if upper.startswith(INSUFFICIENT_EVIDENCE_SENTINEL) and not _MARKER.search(text):
        return ParsedReply("insufficient", "", (), "", "text")
    text = normalize_markers(text)
    if upper.startswith(INSUFFICIENT_EVIDENCE_SENTINEL):
        # Sentinel followed by a (partly) cited answer: keep what is supported.
        text = text[len(INSUFFICIENT_EVIDENCE_SENTINEL) :].lstrip(" :.-\n")
        return ParsedReply("partial", text, (), "", "text")
    return ParsedReply("answered", text, (), "", "text")
