"""The DIP2 indexing pipeline against the real test database (fake embedder, no broker)."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document, DocumentChunk, DocumentProcessingJob
from app.domain.enums import DocumentStatus, JobStatus
from app.storage.local import LocalStorage
from app.workers.processing import JobOutcome
from app.workers.steps import NO_TEXT_MESSAGE
from tests.conftest import RecordingDispatcher, run_indexing, upload_and_index
from tests.factories import DOCX_CONTENT_TYPE, pdf_file
from tests.fakes import HashingEmbeddingProvider
from tests.fixtures.builders import build_docx, build_pdf

SMALL_CHUNKS = get_settings().model_copy(update={"chunk_size": 40, "chunk_overlap": 8})


def _chunks(session: Session, document_id: uuid.UUID) -> list[DocumentChunk]:
    session.expire_all()
    return list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
    )


def _job(session: Session, document_id: uuid.UUID) -> DocumentProcessingJob:
    session.expire_all()
    job = session.scalars(
        select(DocumentProcessingJob)
        .where(DocumentProcessingJob.document_id == document_id)
        .order_by(DocumentProcessingJob.created_at.desc())
    ).first()
    assert job is not None
    return job


def _pdf() -> tuple[str, bytes, str]:
    pages = [
        [f"Page one sentence {i} about the refund policy and returns." for i in range(8)],
        [f"Page two sentence {i} about shipping times and carriers." for i in range(8)],
    ]
    return ("policy.pdf", build_pdf(pages), "application/pdf")


def test_pdf_is_extracted_chunked_embedded_and_indexed(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    db_session: Session,
) -> None:
    document_id, outcome = upload_and_index(
        client, user_headers, dispatcher, storage, embedder, _pdf(), SMALL_CHUNKS
    )
    assert outcome is JobOutcome.COMPLETED
    chunks = _chunks(db_session, document_id)
    assert len(chunks) > 2
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 2
    document = db_session.get(Document, document_id)
    assert document is not None
    assert document.status is DocumentStatus.COMPLETED
    for chunk in chunks:
        assert chunk.owner_id == document.owner_id
        assert len(chunk.embedding) == 384
        assert chunk.embedding_model == "test-hashing-embedder"
        assert 0 < chunk.token_count <= 40
        assert chunk.char_end > chunk.char_start
    job = _job(db_session, document_id)
    assert job.status is JobStatus.COMPLETED
    assert job.stage == "index"

    status = client.get(f"/documents/{document_id}/status", headers=user_headers).json()
    assert status["chunk_count"] == len(chunks)
    assert status["job"]["stage"] == "index"


def test_docx_and_txt_are_indexed(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    db_session: Session,
) -> None:
    docx = ("notes.docx", build_docx(["Heading", "Body paragraph text."]), DOCX_CONTENT_TYPE)
    txt = ("notes.txt", b"Plain text content for indexing.", "text/plain")
    for file in (docx, txt):
        document_id, outcome = upload_and_index(
            client, user_headers, dispatcher, storage, embedder, file
        )
        assert outcome is JobOutcome.COMPLETED
        chunks = _chunks(db_session, document_id)
        assert len(chunks) == 1
        assert chunks[0].page_start is None


def test_pdf_without_text_fails_with_safe_reason(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    db_session: Session,
) -> None:
    scanned = ("scan.pdf", build_pdf([[], []]), "application/pdf")  # pages, no text layer
    document_id, outcome = upload_and_index(
        client, user_headers, dispatcher, storage, embedder, scanned
    )
    assert outcome is JobOutcome.FAILED
    job = _job(db_session, document_id)
    assert job.status is JobStatus.FAILED
    assert job.error_message == NO_TEXT_MESSAGE
    assert job.stage == "normalize"
    assert _chunks(db_session, document_id) == []
    assert embedder.calls == []  # never reached the embedding step


def test_corrupt_pdf_fails_permanently(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    db_session: Session,
) -> None:
    # DIP1's upload fixture: valid magic bytes but no xref table / pages.
    document_id, outcome = upload_and_index(
        client, user_headers, dispatcher, storage, embedder, pdf_file()
    )
    assert outcome is JobOutcome.FAILED
    job = _job(db_session, document_id)
    assert job.error_message == "The PDF could not be read (corrupt or unsupported)"
    assert job.stage == "extract"
    assert job.attempts == 1  # permanent: not retried


def test_too_many_chunks_fails(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    db_session: Session,
) -> None:
    limited = SMALL_CHUNKS.model_copy(update={"max_chunks_per_document": 2})
    document_id, outcome = upload_and_index(
        client, user_headers, dispatcher, storage, embedder, _pdf(), limited
    )
    assert outcome is JobOutcome.FAILED
    assert _job(db_session, document_id).error_message == (
        "The document is too large to index (more than 2 chunks)"
    )


def test_embedding_failure_marks_failed_not_stuck(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    db_session: Session,
) -> None:
    failing = HashingEmbeddingProvider(fail=True)
    document_id, outcome = upload_and_index(
        client, user_headers, dispatcher, storage, failing, _pdf()
    )
    assert outcome is JobOutcome.FAILED
    job = _job(db_session, document_id)
    assert job.status is JobStatus.FAILED
    assert job.stage == "embed"
    assert job.error_message == "Processing failed due to an internal error"
    document = db_session.get(Document, document_id)
    assert document is not None
    assert document.status is DocumentStatus.FAILED


def test_reprocessing_is_idempotent(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    db_session: Session,
) -> None:
    document_id, _ = upload_and_index(
        client, user_headers, dispatcher, storage, embedder, _pdf(), SMALL_CHUNKS
    )
    first = [(c.chunk_index, c.content, c.id) for c in _chunks(db_session, document_id)]

    response = client.post(f"/documents/{document_id}/reprocess", headers=user_headers)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    # A second request while queued is rejected.
    assert (
        client.post(f"/documents/{document_id}/reprocess", headers=user_headers).status_code == 409
    )
    new_job_id = uuid.UUID(response.json()["job_id"])
    assert dispatcher.calls[-1]["job_id"] == new_job_id
    assert run_indexing(new_job_id, storage, embedder, SMALL_CHUNKS) is JobOutcome.COMPLETED

    second = [(c.chunk_index, c.content, c.id) for c in _chunks(db_session, document_id)]
    assert [(i, t) for i, t, _ in second] == [(i, t) for i, t, _ in first]
    assert {cid for *_, cid in second}.isdisjoint({cid for *_, cid in first})  # rebuilt
    # Re-running the same (now terminal) job is a no-op.
    assert run_indexing(new_job_id, storage, embedder, SMALL_CHUNKS) is JobOutcome.SKIPPED
    assert len(_chunks(db_session, document_id)) == len(first)


def test_reprocess_requires_ownership(
    client: TestClient,
    user_headers: dict[str, str],
    other_user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> None:
    document_id, _ = upload_and_index(client, user_headers, dispatcher, storage, embedder, _pdf())
    response = client.post(f"/documents/{document_id}/reprocess", headers=other_user_headers)
    assert response.status_code == 404
    assert client.post(f"/documents/{document_id}/reprocess").status_code == 401


def test_deleting_document_removes_chunks(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    db_session: Session,
) -> None:
    document_id, _ = upload_and_index(
        client, user_headers, dispatcher, storage, embedder, _pdf(), SMALL_CHUNKS
    )
    assert _chunks(db_session, document_id)
    assert client.delete(f"/documents/{document_id}", headers=user_headers).status_code == 204
    assert _chunks(db_session, document_id) == []


def test_index_step_skips_document_deleted_mid_run(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    db_session: Session,
) -> None:
    """Deleting the document while the worker embeds must not crash or leave chunks."""
    response = client.post("/documents", files={"file": _pdf()}, headers=user_headers)
    document_id = uuid.UUID(response.json()["id"])
    job_id = dispatcher.calls[-1]["job_id"]

    class _DeletingEmbedder(HashingEmbeddingProvider):
        def embed(self, texts: list[str]) -> list[list[float]]:  # type: ignore[override]
            client.delete(f"/documents/{document_id}", headers=user_headers)
            return super().embed(texts)

    outcome = run_indexing(job_id, storage, _DeletingEmbedder())  # type: ignore[arg-type]
    assert outcome is JobOutcome.COMPLETED  # nothing left to update; finishes quietly
    assert _chunks(db_session, document_id) == []
