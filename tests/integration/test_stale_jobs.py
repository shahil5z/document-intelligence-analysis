"""Stale-job reconciliation against the real test database (app/workers/reconcile.py)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import main as cli_main
from app.core.config import SettingsError, load_settings
from app.db.models import Document, DocumentProcessingJob
from app.db.session import get_session_factory
from app.domain.enums import DocumentStatus, JobStatus
from app.storage.local import LocalStorage
from app.workers.pipeline import DocumentPipeline
from app.workers.processing import (
    RETRIES_EXHAUSTED_MESSAGE,
    STALE_JOB_MESSAGE,
    DocumentProcessor,
)
from app.workers.reconcile import reconcile_stale_jobs
from tests.conftest import RecordingDispatcher
from tests.factories import pdf_file

TIMEOUT = 900


def _upload(
    client: TestClient, headers: dict[str, str], dispatcher: RecordingDispatcher, name: str
) -> tuple[uuid.UUID, uuid.UUID]:
    response = client.post(
        "/documents", files={"file": pdf_file(name, name.encode())}, headers=headers
    )
    assert response.status_code == 201, response.text
    call = dispatcher.calls[-1]
    return call["document_id"], call["job_id"]  # type: ignore[return-value]


def _set_state(
    doc_id: uuid.UUID, job_id: uuid.UUID, job_status: JobStatus, doc_status: DocumentStatus
) -> None:
    with get_session_factory()() as session:
        job = session.get(DocumentProcessingJob, job_id)
        document = session.get(Document, doc_id)
        assert job is not None
        assert document is not None
        job.status = job_status
        job.started_at = datetime.now(UTC)
        document.status = doc_status
        session.commit()


def _state(session: Session, doc_id: uuid.UUID, job_id: uuid.UUID) -> tuple[str, str, str | None]:
    session.expire_all()
    job = session.get(DocumentProcessingJob, job_id)
    document = session.get(Document, doc_id)
    assert job is not None
    assert document is not None
    return job.status.value, document.status.value, job.error_message


def _later(seconds: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def test_stale_processing_and_retrying_jobs_are_failed_fresh_and_finished_ones_kept(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    db_session: Session,
) -> None:
    processing = _upload(client, user_headers, dispatcher, "processing.pdf")
    retrying = _upload(client, user_headers, dispatcher, "retrying.pdf")
    queued = _upload(client, user_headers, dispatcher, "queued.pdf")
    completed = _upload(client, user_headers, dispatcher, "completed.pdf")
    _set_state(*processing, JobStatus.PROCESSING, DocumentStatus.PROCESSING)
    _set_state(*retrying, JobStatus.PROCESSING, DocumentStatus.PROCESSING)
    _set_state(*retrying, JobStatus.RETRYING, DocumentStatus.QUEUED)
    _set_state(*completed, JobStatus.PROCESSING, DocumentStatus.PROCESSING)
    _set_state(*completed, JobStatus.COMPLETED, DocumentStatus.COMPLETED)
    factory = get_session_factory()

    # Not stale yet: nothing changes.
    assert reconcile_stale_jobs(factory, timeout_seconds=TIMEOUT, now=_later(TIMEOUT - 60)) == 0
    assert _state(db_session, *processing)[0] == "processing"

    assert reconcile_stale_jobs(factory, timeout_seconds=TIMEOUT, now=_later(TIMEOUT + 60)) == 2
    for ids in (processing, retrying):
        assert _state(db_session, *ids) == ("failed", "failed", STALE_JOB_MESSAGE)
    # Queued jobs may legitimately wait behind a backlog; finished jobs are terminal.
    assert _state(db_session, *queued)[:2] == ("queued", "queued")
    assert _state(db_session, *completed)[:2] == ("completed", "completed")
    # Idempotent.
    assert reconcile_stale_jobs(factory, timeout_seconds=TIMEOUT, now=_later(TIMEOUT + 60)) == 0

    status = client.get(f"/documents/{processing[0]}/status", headers=user_headers).json()
    assert status["status"] == "failed"
    assert status["job"]["error_message"] == STALE_JOB_MESSAGE
    # A failed document can be reprocessed again.
    assert (
        client.post(f"/documents/{processing[0]}/reprocess", headers=user_headers).status_code
        == 202
    )


def test_reconciler_skips_a_job_whose_document_is_locked_by_a_worker(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    db_session: Session,
) -> None:
    ids = _upload(client, user_headers, dispatcher, "locked.pdf")
    _set_state(*ids, JobStatus.PROCESSING, DocumentStatus.PROCESSING)
    factory = get_session_factory()
    with factory() as worker_session:
        # e.g. IndexStep holding the document row while it replaces chunks
        worker_session.scalar(select(Document).where(Document.id == ids[0]).with_for_update())
        assert reconcile_stale_jobs(factory, timeout_seconds=TIMEOUT, now=_later(TIMEOUT + 60)) == 0
        worker_session.rollback()
    assert reconcile_stale_jobs(factory, timeout_seconds=TIMEOUT, now=_later(TIMEOUT + 60)) == 1
    assert _state(db_session, *ids)[0] == "failed"


def test_final_attempt_that_cannot_save_its_result_is_failed_by_mark_failed(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    db_session: Session,
) -> None:
    ids = _upload(client, user_headers, dispatcher, "final.pdf")
    _set_state(*ids, JobStatus.PROCESSING, DocumentStatus.PROCESSING)
    processor = DocumentProcessor(get_session_factory(), storage, DocumentPipeline([]))
    assert processor.mark_failed(ids[1], RETRIES_EXHAUSTED_MESSAGE) is True
    assert _state(db_session, *ids) == ("failed", "failed", RETRIES_EXHAUSTED_MESSAGE)
    # Already terminal: no change, no error.
    assert processor.mark_failed(ids[1], RETRIES_EXHAUSTED_MESSAGE) is False


def test_cli_reconcile_command(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del client, user_headers, dispatcher
    assert cli_main(["reconcile-stale-jobs"]) == 0
    assert "Marked 0 stale job(s) as failed" in capsys.readouterr().out


def test_stale_timeout_must_exceed_the_hard_task_time_limit() -> None:
    with pytest.raises(SettingsError, match="STALE_JOB_TIMEOUT_SECONDS"):
        load_settings(
            _env_file=None,
            app_env="test",
            jwt_secret_key="x" * 40,
            celery_task_time_limit=300,
            stale_job_timeout_seconds=300,
        )
