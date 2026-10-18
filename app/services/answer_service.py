"""Retrieval-augmented question answering with validated citations.

Flow: hybrid retrieval (mandatory) -> evidence threshold on cosine similarity (no LLM call
when nothing qualifies) -> token-budgeted, de-duplicated context -> LLM -> citation
validation against the sources actually sent. A failing LLM yields 503; /search does not
depend on the LLM at all.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from app.ai.base import LLMProvider
from app.ai.errors import LLMError
from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.core.metrics import ASK_REQUESTS
from app.db.models import User
from app.domain.enums import SearchMode
from app.processing.chunking import TokenCounter
from app.services.rag_prompt import (
    INSUFFICIENT_EVIDENCE_SENTINEL,
    ContextSource,
    build_context,
    build_messages,
)
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

INSUFFICIENT_EVIDENCE_ANSWER = (
    "I could not find enough evidence in your documents to answer this question."
)
LLM_UNAVAILABLE_MESSAGE = "The answer service is temporarily unavailable; /search still works"
LLM_NOT_CONFIGURED_MESSAGE = "Question answering is not configured; /search still works"

# [S1], [S1, S3], [S2][S4]
_CITATION_GROUP = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]")
_LABEL = re.compile(r"S\d+")


@dataclass(frozen=True)
class CitedSource:
    label: str
    source: ContextSource


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    insufficient_evidence: bool
    citations: list[CitedSource]
    sources_considered: int
    model: str | None
    warnings: list[str] = field(default_factory=list)


def validate_citations(answer: str, sources: list[ContextSource]) -> tuple[str, list[str], int]:
    """Keep only citation labels that exist in ``sources``.

    Returns the answer with unknown labels removed, the valid labels in order of first
    appearance, and how many invalid labels were removed.
    """
    known = {source.label for source in sources}
    cited: list[str] = []
    removed = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal removed
        labels = _LABEL.findall(match.group(1))
        valid = [label for label in labels if label in known]
        removed += len(labels) - len(valid)
        for label in valid:
            if label not in cited:
                cited.append(label)
        return "".join(f"[{label}]" for label in valid)

    cleaned = _CITATION_GROUP.sub(_replace, answer)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    return cleaned.strip(), cited, removed


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
            top_k=top_k,
            mode=SearchMode.HYBRID,
            document_id=document_id,
        ).results
        threshold = self._settings.min_evidence_similarity
        evidence = [
            item
            for item in retrieved
            if item.hit.similarity is not None and item.hit.similarity >= threshold
        ]
        if not evidence:
            ASK_REQUESTS.labels("insufficient_evidence").inc()
            logger.info(
                "ask.insufficient_evidence",
                extra={"retrieved": len(retrieved), "threshold": threshold, "llm_called": False},
            )
            return AnswerResult(
                answer=INSUFFICIENT_EVIDENCE_ANSWER,
                insufficient_evidence=True,
                citations=[],
                sources_considered=0,
                model=None,
            )

        sources = build_context(
            evidence, max_tokens=self._settings.max_context_tokens, counter=self._counter
        )
        if self._llm is None:
            ASK_REQUESTS.labels("not_configured").inc()
            raise ServiceUnavailableError(LLM_NOT_CONFIGURED_MESSAGE)
        try:
            raw = self._llm.complete(build_messages(question, sources))
        except LLMError as exc:
            ASK_REQUESTS.labels("llm_unavailable").inc()
            logger.warning("ask.llm_failed", extra={"error_type": type(exc).__name__})
            raise ServiceUnavailableError(LLM_UNAVAILABLE_MESSAGE) from exc

        model = self._llm.model_name
        if raw.strip().startswith(INSUFFICIENT_EVIDENCE_SENTINEL) or not raw.strip():
            ASK_REQUESTS.labels("insufficient_evidence").inc()
            logger.info(
                "ask.insufficient_evidence",
                extra={"retrieved": len(retrieved), "llm_called": True},
            )
            return AnswerResult(
                answer=INSUFFICIENT_EVIDENCE_ANSWER,
                insufficient_evidence=True,
                citations=[],
                sources_considered=len(sources),
                model=model,
            )

        answer, labels, removed = validate_citations(raw, sources)
        by_label = {source.label: source for source in sources}
        warnings: list[str] = []
        if removed:
            warnings.append("invalid_citations_removed")
        if not labels:
            warnings.append("answer_has_no_citations")
        ASK_REQUESTS.labels("answered").inc()
        logger.info(
            "ask.completed",
            extra={
                "retrieved": len(retrieved),
                "sources_sent": len(sources),
                "citations": len(labels),
                "invalid_citations_removed": removed,
                "question_length": len(question),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return AnswerResult(
            answer=answer,
            insufficient_evidence=False,
            citations=[CitedSource(label=label, source=by_label[label]) for label in labels],
            sources_considered=len(sources),
            model=model,
            warnings=warnings,
        )
