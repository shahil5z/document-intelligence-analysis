"""DIP3 reliability paths of DocumentProcessor against the real test database."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Document, DocumentProcessingJob
from app.db.session import get_session_factory
from app.domain.enums import DocumentStatus, JobStatus
from app.storage.local import LocalStorage
from app.workers.pipeline import DocumentPipeline, PipelineContext, TransientProcessingError
from app.workers.processing import (
    RETRIES_EXHAUSTED_MESSAGE,
    TIMEOUT_MESSAGE,
    DocumentProcessor,
    JobOutcome,
)
from tests.conftest import RecordingDispatcher
from tests.factories import pdf_file


class _SoftTimeLimit(Exception):  # noqa: N818  (stands in for celery's SoftTimeLimitExceeded)
    pass


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


class _Step:
    name = "noop"

    def __init__(self, action: Any = None) -> None:
        self.action = action
        self.runs = 0

    def run(self, context: PipelineContext) -> None:
        del context
        self.runs += 1
        if self.action is not None:
            self.action()


def test_soft_time_limit_fails_job_with_clear_message(
    uploaded: tuple[uuid.UUID, uuid.UUID], storage: LocalStorage, db_session: Session
) -> None:
    doc_id, job_id = uploaded

    def slow() -> None:
        raise _SoftTimeLimit

    processor = DocumentProcessor(
        get_session_factory(),
        storage,
        DocumentPipeline([_Step(slow)]),
        timeout_errors=(_SoftTimeLimit,),
    )
    assert processor.run(job_id=job_id, is_final_attempt=False) is JobOutcome.FAILED
    document, job = _reload(db_session, doc_id, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error_message == TIMEOUT_MESSAGE
    assert document.status is DocumentStatus.FAILED


def test_redelivery_loop_is_bounded_by_max_attempts(
    uploaded: tuple[uuid.UUID, uuid.UUID], storage: LocalStorage, db_session: Session
) -> None:
    doc_id, job_id = uploaded
    step = _Step()
    processor = DocumentProcessor(
        get_session_factory(), storage, DocumentPipeline([step]), max_attempts=2
    )
    # Simulate two deliveries that were killed (hard time limit) after claiming.
    with get_session_factory()() as session:
        job = session.get(DocumentProcessingJob, job_id)
        document = session.get(Document, doc_id)
        assert job is not None
        assert document is not None
        job.status = JobStatus.PROCESSING
        job.attempts = 2
        document.status = DocumentStatus.PROCESSING
        session.commit()

    assert processor.run(job_id=job_id, is_final_attempt=False) is JobOutcome.SKIPPED
    assert step.runs == 0
    document, job = _reload(db_session, doc_id, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error_message == RETRIES_EXHAUSTED_MESSAGE
    assert document.status is DocumentStatus.FAILED


class _FailingAfterFlag:
    """Session factory that raises OperationalError once ``armed`` is set."""

    def __init__(self, inner: sessionmaker[Session]) -> None:
        self.inner = inner
        self.armed = False

    def __call__(self) -> Session:
        if self.armed:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        return self.inner()


def test_database_outage_when_finishing_becomes_a_retry_then_recovers(
    uploaded: tuple[uuid.UUID, uuid.UUID], storage: LocalStorage, db_session: Session
) -> None:
    doc_id, job_id = uploaded
    factory = _FailingAfterFlag(get_session_factory())

    def arm() -> None:
        factory.armed = True

    step = _Step(arm)
    flaky = DocumentProcessor(factory, storage, DocumentPipeline([step]))  # type: ignore[arg-type]
    with pytest.raises(TransientProcessingError):
        flaky.run(job_id=job_id, is_final_attempt=False)
    document, job = _reload(db_session, doc_id, job_id)
    # Nothing could be written: the job is still "processing" and will be reclaimed.
    assert job.status is JobStatus.PROCESSING
    assert document.status is DocumentStatus.PROCESSING

    healthy = DocumentProcessor(get_session_factory(), storage, DocumentPipeline([_Step()]))
    assert healthy.run(job_id=job_id, is_final_attempt=False) is JobOutcome.COMPLETED
    document, job = _reload(db_session, doc_id, job_id)
    assert job.status is JobStatus.COMPLETED
    assert job.attempts == 2
    assert document.status is DocumentStatus.COMPLETED


def test_transient_failure_records_retrying_and_retry_metric(
    uploaded: tuple[uuid.UUID, uuid.UUID], storage: LocalStorage, db_session: Session
) -> None:
    from prometheus_client import REGISTRY  # noqa: PLC0415

    doc_id, job_id = uploaded

    def flaky() -> None:
        raise TransientProcessingError("redis down")

    before = REGISTRY.get_sample_value("dip_processing_jobs_total", {"outcome": "retry"}) or 0.0
    processor = DocumentProcessor(get_session_factory(), storage, DocumentPipeline([_Step(flaky)]))
    with pytest.raises(TransientProcessingError):
        processor.run(job_id=job_id, is_final_attempt=False)
    document, job = _reload(db_session, doc_id, job_id)
    assert job.status is JobStatus.RETRYING
    assert document.status is DocumentStatus.QUEUED
    after = REGISTRY.get_sample_value("dip_processing_jobs_total", {"outcome": "retry"}) or 0.0
    assert after == before + 1
