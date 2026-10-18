"""POST /search: modes, isolation, filters, validation and deletion (fake embedder)."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.services import get_reranker
from app.storage.local import LocalStorage
from tests.conftest import RecordingDispatcher, upload_and_index
from tests.fakes import HashingEmbeddingProvider, ReverseReranker

REFUND = "Refund policy. Customers may request a refund within 30 days of delivery."
LUNCH = "Cafeteria notice. The cafeteria serves lunch at noon on weekdays."
Indexer = Callable[..., uuid.UUID]
FLAG = "Runbook. Enable the flag payments.fallback_enabled when the processor fails."


@pytest.fixture
def index(
    client: TestClient,
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> Indexer:
    def _index(headers: dict[str, str], text: str, name: str = "doc.txt") -> uuid.UUID:
        document_id, _ = upload_and_index(
            client, headers, dispatcher, storage, embedder, (name, text.encode(), "text/plain")
        )
        return document_id

    return _index


def _search(client: TestClient, headers: dict[str, str], **body: object) -> dict[str, Any]:
    response = client.post("/search", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


@pytest.mark.parametrize("mode", ["semantic", "keyword", "hybrid"])
def test_each_mode_finds_the_relevant_document(
    client: TestClient,
    user_headers: dict[str, str],
    index: Indexer,
    mode: str,
) -> None:
    refund_id = index(user_headers, REFUND, "refund.txt")
    index(user_headers, LUNCH, "lunch.txt")
    body = _search(client, user_headers, query="refund within 30 days", mode=mode, top_k=5)
    assert body["mode"] == mode
    assert body["results"], body
    top = body["results"][0]
    assert top["document_id"] == str(refund_id)
    assert top["filename"] == "refund.txt"
    assert top["text"] == REFUND
    assert top["char_start"] == 0
    assert "embedding" not in top
    if mode == "keyword":
        assert all(r["filename"] == "refund.txt" for r in body["results"])
        assert top["keyword_rank"] == 1
    if mode == "semantic":
        assert top["similarity"] == pytest.approx(top["score"])
    if mode == "hybrid":
        assert top["semantic_rank"] == 1
        assert top["keyword_rank"] == 1


def test_keyword_mode_matches_exact_identifiers(
    client: TestClient,
    user_headers: dict[str, str],
    index: Indexer,
) -> None:
    index(user_headers, FLAG, "runbook.txt")
    index(user_headers, LUNCH, "lunch.txt")
    body = _search(client, user_headers, query="payments.fallback_enabled", mode="keyword")
    assert [r["filename"] for r in body["results"]] == ["runbook.txt"]


def test_results_are_isolated_per_user(
    client: TestClient,
    user_headers: dict[str, str],
    other_user_headers: dict[str, str],
    index: Indexer,
) -> None:
    index(user_headers, REFUND, "alice.txt")
    for mode in ("semantic", "keyword", "hybrid"):
        body = _search(client, other_user_headers, query="refund within 30 days", mode=mode)
        assert body["results"] == []


def test_document_filter_and_foreign_document(
    client: TestClient,
    user_headers: dict[str, str],
    other_user_headers: dict[str, str],
    index: Indexer,
) -> None:
    refund_id = index(user_headers, REFUND, "refund.txt")
    lunch_id = index(user_headers, LUNCH, "lunch.txt")
    body = _search(client, user_headers, query="refund", mode="semantic", document_id=str(lunch_id))
    assert {r["document_id"] for r in body["results"]} <= {str(lunch_id)}
    # Another user's document id behaves like a missing one.
    response = client.post(
        "/search",
        json={"query": "refund", "document_id": str(refund_id)},
        headers=other_user_headers,
    )
    assert response.status_code == 404


def test_deleted_document_is_no_longer_searchable(
    client: TestClient,
    user_headers: dict[str, str],
    index: Indexer,
) -> None:
    refund_id = index(user_headers, REFUND, "refund.txt")
    assert _search(client, user_headers, query="refund", mode="keyword")["results"]
    assert client.delete(f"/documents/{refund_id}", headers=user_headers).status_code == 204
    for mode in ("semantic", "keyword", "hybrid"):
        assert _search(client, user_headers, query="refund", mode=mode)["results"] == []


def test_documents_not_completed_are_excluded(
    client: TestClient,
    user_headers: dict[str, str],
    index: Indexer,
) -> None:
    refund_id = index(user_headers, REFUND, "refund.txt")
    response = client.post(f"/documents/{refund_id}/reprocess", headers=user_headers)
    assert response.status_code == 202
    # Chunks still exist but the document is queued, so it must not be searchable.
    status = client.get(f"/documents/{refund_id}/status", headers=user_headers).json()
    assert status["status"] == "queued"
    assert status["chunk_count"] >= 1
    assert _search(client, user_headers, query="refund", mode="hybrid")["results"] == []


def test_top_k_and_ordering_are_deterministic(
    client: TestClient,
    user_headers: dict[str, str],
    index: Indexer,
) -> None:
    for i in range(5):
        index(user_headers, f"Document {i} mentions refund rules number {i}.", f"d{i}.txt")
    first = _search(client, user_headers, query="refund rules", mode="hybrid", top_k=3)
    second = _search(client, user_headers, query="refund rules", mode="hybrid", top_k=3)
    assert len(first["results"]) == 3
    assert [r["chunk_id"] for r in first["results"]] == [r["chunk_id"] for r in second["results"]]
    assert len({r["chunk_id"] for r in first["results"]}) == 3


@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 1001},
        {"query": "ok", "top_k": 0},
        {"query": "ok", "top_k": 21},
        {"query": "ok", "mode": "fuzzy"},
        {"query": "ok", "unexpected": 1},
    ],
)
def test_validation_errors(
    client: TestClient, user_headers: dict[str, str], body: dict[str, object]
) -> None:
    response = client.post("/search", json=body, headers=user_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_search_requires_authentication(client: TestClient) -> None:
    response = client.post("/search", json={"query": "refund"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_embedding_outage_returns_503_but_keyword_still_works(
    client: TestClient,
    user_headers: dict[str, str],
    embedder: HashingEmbeddingProvider,
    index: Indexer,
) -> None:
    index(user_headers, REFUND, "refund.txt")
    embedder.fail = True
    for mode in ("semantic", "hybrid"):
        response = client.post(
            "/search", json={"query": "refund", "mode": mode}, headers=user_headers
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "service_unavailable"
    assert _search(client, user_headers, query="refund", mode="keyword")["results"]


def test_optional_reranker_reorders_results(
    app: FastAPI, client: TestClient, user_headers: dict[str, str], index: Indexer
) -> None:
    index(user_headers, "refund short.", "short.txt")
    index(user_headers, "refund " + "with a much longer explanation " * 5, "long.txt")
    reranker = ReverseReranker()
    app.dependency_overrides[get_reranker] = lambda: reranker
    body = _search(client, user_headers, query="refund", mode="hybrid", top_k=2)
    assert body["reranked"] is True
    assert reranker.calls == 1
    assert [r["filename"] for r in body["results"]] == ["long.txt", "short.txt"]
