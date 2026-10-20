"""Suggested questions through the real pipeline, database and API (mock LLM)."""

import json

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.enums import JobStatus
from app.storage.local import LocalStorage
from app.workers.processing import JobOutcome
from tests.conftest import RecordingDispatcher, run_indexing
from tests.fakes import HashingEmbeddingProvider, MockLLM

QUESTIONS = [
    "How many days do customers have to return items?",
    "Are refunds issued to the original payment method?",
    "Who pays for return shipping?",
]
TXT = (
    "refunds.txt",
    b"Customers may return unused items within 30 days. Refunds go to the original "
    b"payment method. Return shipping is paid by the customer.",
    "text/plain",
)


def _upload(client: TestClient, headers: dict[str, str], dispatcher: RecordingDispatcher):  # type: ignore[no-untyped-def]
    response = client.post("/documents", files={"file": TXT}, headers=headers)
    assert response.status_code == 201, response.text
    return dispatcher.calls[-1]


def test_migration_adds_a_nullable_jsonb_column(db_session: Session) -> None:
    row = db_session.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'documents' AND column_name = 'suggested_questions'"
        )
    ).one()
    assert tuple(row) == ("jsonb", "YES")
    assert db_session.scalar(text("SELECT version_num FROM alembic_version")) == "0004"


def test_questions_are_stored_and_returned_by_the_api(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> None:
    call = _upload(client, user_headers, dispatcher)
    llm = MockLLM(response=json.dumps({"questions": QUESTIONS}))
    outcome = run_indexing(call["job_id"], storage, embedder, suggestion_llm=llm)
    assert outcome is JobOutcome.COMPLETED
    assert "30 days" in llm.calls[0][1]["content"]

    document_id = call["document_id"]
    detail = client.get(f"/documents/{document_id}", headers=user_headers).json()
    assert detail["suggested_questions"] == QUESTIONS
    listing = client.get("/documents", headers=user_headers).json()
    items = listing["items"] if isinstance(listing, dict) else listing
    assert items[0]["suggested_questions"] == QUESTIONS


def test_llm_failure_keeps_the_job_completed_and_the_field_null(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> None:
    call = _upload(client, user_headers, dispatcher)
    outcome = run_indexing(call["job_id"], storage, embedder, suggestion_llm=MockLLM(error=True))
    assert outcome is JobOutcome.COMPLETED
    document_id = call["document_id"]
    status = client.get(f"/documents/{document_id}/status", headers=user_headers).json()
    assert status["job"]["status"] == JobStatus.COMPLETED.value
    detail = client.get(f"/documents/{document_id}", headers=user_headers).json()
    assert detail["suggested_questions"] is None


def test_without_an_llm_the_field_stays_null(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> None:
    call = _upload(client, user_headers, dispatcher)
    assert run_indexing(call["job_id"], storage, embedder) is JobOutcome.COMPLETED
    detail = client.get(f"/documents/{call['document_id']}", headers=user_headers).json()
    assert detail["suggested_questions"] is None
