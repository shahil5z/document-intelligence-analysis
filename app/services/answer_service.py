"""Retrieval-augmented question answering with validated citations.

Flow: hybrid retrieval (mandatory) -> evidence gate on the best cosine similarity (no
LLM call when nothing qualifies) -> token-budgeted, de-duplicated context of the
supporting passages -> LLM (structured output requested) -> tolerant parsing
(``answer_parsing``) -> citation validation against the sources actually sent.

Outcome rules:

* below_threshold: best similarity < the gate, no LLM call. The gate is
  MIN_EVIDENCE_SIMILARITY, or the lower ASK_SCOPED_MIN_SIMILARITY when the question is
  scoped to one document or asks about the document as a whole (see
  ``is_document_level_question``);
* answered / partial: the reply has at least one valid citation; invalid citations are
  dropped and reported in ``warnings``; ``partial`` keeps the supported answer and says
  what is missing;
* insufficient with a reason: ``model_declined`` (model said no source is relevant and
  cited nothing), ``parse_failed`` (empty/unusable reply) or ``no_valid_citations``
  (an answer that cites nothing that was sent - treated as ungrounded).

A failing LLM yields 503; /search does not depend on the LLM at all. Reasons, counts
and the prompt version are logged; questions, passages and answers never are.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.ai.base import LLMProvider
from app.ai.errors import LLMError
from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.core.metrics import ASK_REQUESTS
from app.db.models import User
from app.domain.enums import SearchMode
from app.processing.chunking import TokenCounter
from app.prompt import PROMPT_VERSION, insufficient_evidence_answer, response_schema
from app.services.answer_parsing import (
    MAX_SOURCE_NUMBER,
    markers_in,
    normalize_markers,
    parse_reply,
)
from app.services.rag_prompt import ContextSource, build_context, build_messages
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

LLM_UNAVAILABLE_MESSAGE = "The answer service is temporarily unavailable; /search still works"
LLM_NOT_CONFIGURED_MESSAGE = "Question answering is not configured; /search still works"

InsufficientReason = Literal[
    "below_threshold", "model_declined", "parse_failed", "no_valid_citations"
]


# Questions about a document as a whole: they match no single passage strongly.
_DOCUMENT_LEVEL = re.compile(
    r"\b(?:summari[sz]e|summary|overview|tl;?dr|gist|outline)\b"
    r"|\b(?:main|key)\s+(?:points?|ideas?|topics?|takeaways?|themes?|findings?)\b"
    r"|\b(?:this|the|my|that)\s+(?:document|file|pdf|text|paper|report|policy|contract)\b"
    r"|\bwhat\s+is\s+(?:it|this)\s+about\b",
    re.IGNORECASE,
)


def is_document_level_question(question: str) -> bool:
    """True for questions about a whole document (summaries, "what is this about")."""
    return _DOCUMENT_LEVEL.search(question) is not None


# User-facing text; it lives in app/prompt/insufficient_evidence.md.
INSUFFICIENT_EVIDENCE_ANSWER = insufficient_evidence_answer()


@dataclass(frozen=True)
class CitedSource:
    label: str
    number: int
    source: ContextSource


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    insufficient_evidence: bool
    citations: list[CitedSource]
    sources_considered: int
    model: str | None
    warnings: list[str] = field(default_factory=list)
    partial: bool = False
    missing_information: str | None = None
    insufficient_reason: InsufficientReason | None = None
    prompt_version: str = PROMPT_VERSION


def validate_citations(answer: str, sources: list[ContextSource]) -> tuple[str, list[int], int]:
    """Keep only citation numbers that refer to a source that was sent.

    ``answer`` may use any marker style (normalised to ``[n]`` first). Returns the
    answer with unknown numbers removed, the valid numbers in order of first
    appearance, and how many invalid markers were removed.
    """
    known = {source.number for source in sources}
    text = normalize_markers(answer)
    removed = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal removed
        number = int(match.group(1))
        if number in known or number > MAX_SOURCE_NUMBER:  # big numbers are plain text
            return match.group(0)
        removed += 1
        return ""

    cleaned = re.sub(r"\[(\d+)\]", _replace, text)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip(), [n for n in markers_in(cleaned) if n in known], removed


class AnswerService:
    def __init__(
        self,
        search: SearchService,
        settings: Settings,
        llm: LLMProvider | None,
        token_counter: TokenCounter,
    ) -> None:
        self._search = search
        self._settings = settings
        self._llm = llm
        self._counter = token_counter

    def _insufficient(
        self,
        reason: InsufficientReason,
        *,
        retrieved: int,
        sources: int,
        model: str | None,
        extra: dict[str, object] | None = None,
    ) -> AnswerResult:
        ASK_REQUESTS.labels("insufficient_evidence").inc()
        logger.info(
            "ask.insufficient_evidence",
            extra={
                "reason": reason,
                "retrieved": retrieved,
                "sources_sent": sources,
                "llm_called": model is not None,
                "prompt_version": PROMPT_VERSION,
                **(extra or {}),
            },
        )
        return AnswerResult(
            answer=INSUFFICIENT_EVIDENCE_ANSWER,
            insufficient_evidence=True,
            citations=[],
            sources_considered=sources,
            model=model,
            insufficient_reason=reason,
        )

    def ask(
        self,
        *,
        owner: User,
        question: str,
        top_k: int | None = None,
        document_id: uuid.UUID | None = None,
    ) -> AnswerResult:
        started = time.perf_counter()
        question = self._search.validate_query(question)
        retrieved = self._search.search(
            owner=owner,
            query=question,
            top_k=top_k or self._settings.ask_top_k,
            mode=SearchMode.HYBRID,
            document_id=document_id,
        ).results
        gate = (
            "scoped"
            if document_id is not None
            else "document_level"
            if is_document_level_question(question)
            else "default"
        )
        threshold = self._settings.min_evidence_similarity
        if gate != "default":
            threshold = min(threshold, self._settings.ask_scoped_min_similarity)
        best = max((item.hit.similarity or -1.0 for item in retrieved), default=-1.0)
        if best < threshold:
            return self._insufficient(
                "below_threshold",
                retrieved=len(retrieved),
                sources=0,
                model=None,
                extra={"threshold": threshold, "best_similarity": round(best, 3), "gate": gate},
            )
        # Context floor: passages that may support the answer once the gate passed. A
        # scoped question sends everything retrieved from that one document down to the
        # gate; an unscoped document-level question never adds passages below the normal
        # floor (other documents' noise), only the best one when it is lower.
        floor = min(self._settings.ask_context_min_similarity, threshold)
        if gate == "document_level":
            floor = min(self._settings.ask_context_min_similarity, best)
        evidence = [
            item
            for item in retrieved
            if item.hit.similarity is not None and item.hit.similarity >= floor
        ]
        sources = build_context(
            evidence, max_tokens=self._settings.max_context_tokens, counter=self._counter
        )
        if self._llm is None:
            ASK_REQUESTS.labels("not_configured").inc()
            raise ServiceUnavailableError(LLM_NOT_CONFIGURED_MESSAGE)
        try:
            raw = self._llm.complete(
                build_messages(question, sources), json_schema=response_schema()
            )
        except LLMError as exc:
            ASK_REQUESTS.labels("llm_unavailable").inc()
            logger.warning("ask.llm_failed", extra={"error_type": type(exc).__name__})
            raise ServiceUnavailableError(LLM_UNAVAILABLE_MESSAGE) from exc

        model = self._llm.model_name
        reply = parse_reply(raw)
        answer, numbers, removed = validate_citations(reply.answer, sources)
        declared = [n for n in reply.declared_citations if n in {s.number for s in sources}]
        diagnostics: dict[str, object] = {
            "parse_mode": reply.mode,
            "model_status": reply.status,
            "invalid_citations_removed": removed,
            "gate": gate,
            "best_similarity": round(best, 3),
        }
        if reply.mode == "empty" or (not answer and reply.status != "insufficient"):
            return self._insufficient(
                "parse_failed",
                retrieved=len(retrieved),
                sources=len(sources),
                model=model,
                extra=diagnostics,
            )
        if not numbers:
            reason: InsufficientReason = (
                "model_declined" if reply.status == "insufficient" else "no_valid_citations"
            )
            return self._insufficient(
                reason,
                retrieved=len(retrieved),
                sources=len(sources),
                model=model,
                extra={**diagnostics, "declared_citations": len(declared)},
            )

        by_number = {source.number: source for source in sources}
        warnings: list[str] = []
        if removed:
            warnings.append("invalid_citations_removed")
        partial = reply.status in ("partial", "insufficient")
        if partial:
            warnings.append("partial_answer")
        ASK_REQUESTS.labels("answered").inc()
        logger.info(
            "ask.completed",
            extra={
                "retrieved": len(retrieved),
                "sources_sent": len(sources),
                "citations": len(numbers),
                "partial": partial,
                "question_length": len(question),
                "prompt_version": PROMPT_VERSION,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                **diagnostics,
            },
        )
        return AnswerResult(
            answer=answer,
            insufficient_evidence=False,
            citations=[
                CitedSource(label=by_number[n].label, number=n, source=by_number[n])
                for n in numbers
            ],
            sources_considered=len(sources),
            model=model,
            warnings=warnings,
            partial=partial,
            missing_information=(reply.missing_information or None) if partial else None,
        )
