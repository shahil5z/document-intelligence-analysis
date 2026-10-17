"""DocumentProcessor against the real test database and local storage (no broker)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentProcessingJob
from app.db.session import get_session_factory
from app.domain.enums import DocumentStatus, JobStatus
from app.storage.local import LocalStorage
from app.workers.pipeline import (
    DocumentPipeline,
    PipelineContext,
    TransientProcessingError,
    build_default_pipeline,
)
from app.workers.processing import DocumentProcessor, JobOutcome
from tests.conftest import RecordingDispatcher
from tests.factories import pdf_file


@pytest.fixture
def uploaded(
    client: TestClient, user_headers: dict[str, str], dispatcher: RecordingDispatcher
) -> tuple[uuid.UUID, uuid.UUID]:
    response = client.post("/documents", files={"file": pdf_file()}, headers=user_headers)
    assert response.status_code == 201
    call = dispatcher.calls[-1]
    return call["document_id"], call["job_id"]  # type: ignore[return-value]


def _reload(
    session: Session, doc_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[Document, DocumentProcessingJob]:
    session.expire_all()
    document = session.get(Document, doc_id)
    job = session.get(DocumentProcessingJob, job_id)
    assert document is not None
    assert job is not None
    return document, job


def test_job_completes_and_is_idempotent(
    uploaded: tuple[uuid.UUID, uuid.UUID], storage: LocalStorage, db_session: Session
) -> None:
    doc_id, job_id = uploaded
    processor = DocumentProcessor(get_session_factory(), storage, build_default_pipeline())
    assert processor.run(job_id=job_id, is_final_attempt=False) is JobOutcome.COMPLETED
    document, job = _reload(db_session, doc_id, job_id)
    assert document.status is DocumentStatus.COMPLETED
    assert job.status is JobStatus.COMPLETED
    assert job.attempts == 1
    assert job.started_at is not None
    assert job.completed_at is not None
    # A redelivered task must not reprocess a finished job.
    assert processor.run(job_id=job_id, is_final_attempt=False) is JobOutcome.SKIPPED


def test_missing_file_fails_with_safe_message(
    uploaded: tuple[uuid.UUID, uuid.UUID], storage: LocalStorage, db_session: Session
) -> None:
    doc_id, job_id = uploaded
    document, _ = _reload(db_session, doc_id, job_id)
    storage.delete(document.storage_key)
    processor = DocumentProcessor(get_session_factory(), storage, build_default_pipeline())
    assert processor.run(job_id=job_id, is_final_attempt=False) is JobOutcome.FAILED
    document, job = _reload(db_session, doc_id, job_id)
    assert document.status is DocumentStatus.FAILED
    assert job.error_message == "The stored file could not be found"


def test_tampered_file_fails_integrity_check(
    uploaded: tuple[uuid.UUID, uuid.UUID], storage: LocalStorage, db_session: Session
) -> None:
    doc_id, job_id = uploaded
    document, _ = _reload(db_session, doc_id, job_id)
    storage.save(document.storage_key, [b"%PDF-tampered"])
    processor = DocumentProcessor(get_session_factory(), storage, build_default_pipeline())
    assert processor.run(job_id=job_id, is_final_attempt=False) is JobOutcome.FAILED
    _, job = _reload(db_session, doc_id, job_id)
    assert job.error_message == "The stored file failed integrity verification"


class _FlakyStep:
    name = "flaky"

    def run(self, context: PipelineContext) -> None:
        del context
        raise TransientProcessingError("temporarily unavailable")


def test_transient_failure_retries_then_fails_on_final_attempt(
    uploaded: tuple[uuid.UUID, uuid.UUID], storage: LocalStorage, db_session: Session
) -> None:
    doc_id, job_id = uploaded
    processor = DocumentProcessor(get_session_factory(), storage, DocumentPipeline([_FlakyStep()]))

    with pytest.raises(TransientProcessingError):
        processor.run(job_id=job_id, is_final_attempt=False)
    document, job = _reload(db_session, doc_id, job_id)
    assert job.status is JobStatus.RETRYING
    assert document.status is DocumentStatus.QUEUED

    assert processor.run(job_id=job_id, is_final_attempt=True) is JobOutcome.FAILED
    document, job = _reload(db_session, doc_id, job_id)
    assert job.status is JobStatus.FAILED
    assert job.attempts == 2
    assert job.error_message == "Processing failed after several attempts"
    assert document.status is DocumentStatus.FAILED


class _BuggyStep:
    name = "buggy"

    def run(self, context: PipelineContext) -> None:
        del context
        raise ValueError("internal detail that must not leak")


def test_unexpected_error_is_not_leaked(
    uploaded: tuple[uuid.UUID, uuid.UUID], storage: LocalStorage, db_session: Session
) -> None:
    doc_id, job_id = uploaded
    processor = DocumentProcessor(get_session_factory(), storage, DocumentPipeline([_BuggyStep()]))
    assert processor.run(job_id=job_id, is_final_attempt=False) is JobOutcome.FAILED
    _, job = _reload(db_session, doc_id, job_id)
    assert job.error_message == "Processing failed due to an internal error"


def test_unknown_job_is_skipped(storage: LocalStorage) -> None:
    processor = DocumentProcessor(get_session_factory(), storage, build_default_pipeline())
    assert processor.run(job_id=uuid.uuid4(), is_final_attempt=False) is JobOutcome.SKIPPED
