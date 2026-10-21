"""Replay realistic LLM replies through the real HTTP client, parser and AnswerService.

Fixture: ``tests/fixtures/llm_replies.json`` (hand-written replicas of gpt-4o-mini
reply formats - see its description). Each reply is served by ``httpx2.MockTransport``
inside a full ``chat.completion`` envelope, so the path is exactly the production one:
OpenAICompatibleLLMProvider -> parse_reply -> validate_citations -> outcome rules.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.ai.llm import OpenAICompatibleLLMProvider
from app.core.config import get_settings
from app.db.repositories.chunks import ChunkHit
from app.domain.enums import SearchMode
from app.processing.chunking import ApproximateTokenCounter
from app.prompt import PROMPT_VERSION
from app.services.answer_format import strip_citation_markers
from app.services.answer_service import INSUFFICIENT_EVIDENCE_ANSWER, AnswerService
from app.services.retrieval import RankedChunk
from app.services.search_service import SearchResult

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "llm_replies.json"
CASES: list[dict[str, Any]] = json.loads(FIXTURE.read_text("utf-8"))["cases"]
PASSAGES = [
    "Customers may return unused items within 30 days of delivery for a full refund.",
    "Refunds are issued to the original payment method within 5-7 business days.",
    "Damaged items must be reported within 48 hours with photos of the packaging.",
]


def _hit(n: int, content: str, similarity: float) -> RankedChunk:
    return RankedChunk(
        hit=ChunkHit(
            chunk_id=uuid.UUID(int=n),
            document_id=uuid.UUID(int=1),
            filename="refund-policy.pdf",
            chunk_index=n,
            content=content,
            page_start=n,
            page_end=n,
            char_start=n * 1000,
            char_end=n * 1000 + len(content),
            token_count=20,
            similarity=similarity,
            keyword_score=None,
        ),
        score=1.0 / n,
    )


class _Search:
    def __init__(self) -> None:
        # A document-level question: best passage just above the threshold, the others
        # below it but above ASK_CONTEXT_MIN_SIMILARITY (all three are sent).
        self.results = [
            _hit(1, PASSAGES[0], 0.53),
            _hit(2, PASSAGES[1], 0.46),
            _hit(3, PASSAGES[2], 0.43),
        ]
        self.calls: list[dict[str, Any]] = []

    def validate_query(self, query: str) -> str:
        return query.strip()

    def search(self, **kwargs: Any) -> SearchResult:
        self.calls.append(kwargs)
        return SearchResult(mode=SearchMode.HYBRID, results=self.results, reranked=False)


def _envelope(content: str | None, refusal: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-replay",
        "object": "chat.completion",
        "created": 1760000000,
        "model": "gpt-4o-mini-2024-07-18",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
                "logprobs": None,
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 900, "completion_tokens": 80, "total_tokens": 980},
        "system_fingerprint": "fp_replay",
    }


def _run(case: dict[str, Any]) -> tuple[Any, list[dict[str, Any]], _Search]:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=_envelope(case["content"], case.get("refusal")))

    llm = OpenAICompatibleLLMProvider(
        api_key="sk-test-replay",
        model="gpt-4o-mini",
        base_url="https://api.openai.test/v1",
        timeout_seconds=5,
        max_output_tokens=900,
        temperature=0.0,
        transport=httpx2.MockTransport(handler),
    )
    settings = get_settings().model_copy(
        update={"min_evidence_similarity": 0.48, "ask_context_min_similarity": 0.40}
    )
    search = _Search()
    service = AnswerService(search, settings, llm, ApproximateTokenCounter())  # type: ignore[arg-type]
    owner: Any = object()
    return service.ask(owner=owner, question="What does the refund policy say?"), sent, search


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_replayed_reply(case: dict[str, Any]) -> None:
    result, sent, search = _run(case)
    expect = case["expect"]
    assert result.insufficient_evidence is expect["insufficient"]
    assert result.prompt_version == PROMPT_VERSION
    assert result.model == "gpt-4o-mini"
    if expect["insufficient"]:
        assert result.insufficient_reason == expect["reason"]
        assert result.answer == INSUFFICIENT_EVIDENCE_ANSWER
        assert result.citations == []
        return
    assert [c.number for c in result.citations] == expect["citations"]
    assert [c.label for c in result.citations] == [f"S{n}" for n in expect["citations"]]
    assert result.partial is expect.get("partial", False)
    if "missing" in expect:
        assert result.missing_information == expect["missing"]
    if "contains" in expect:
        assert strip_citation_markers(expect["contains"]) in result.answer
    for warning in expect.get("warnings", []):
        assert warning in result.warnings
    # Grounding is checked on the markers; the returned text is clean Markdown without them.
    import re  # noqa: PLC0415

    assert not [n for n in re.findall(r"\[(\d+)\]", result.answer) if int(n) <= 100]
    # The request: structured output schema, all three passages, ask_top_k default.
    body = sent[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    user = body["messages"][1]["content"]
    assert user.count("<source id=") == 3
    assert search.calls[0]["top_k"] == get_settings().ask_top_k


def test_fixture_covers_every_reason() -> None:
    reasons = {c["expect"].get("reason") for c in CASES if c["expect"]["insufficient"]}
    assert reasons == {"model_declined", "parse_failed", "no_valid_citations"}
