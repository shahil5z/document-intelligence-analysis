"""Celery task adapter and dispatcher without a broker or database.

``process_document`` is called directly (Celery's ``called_directly`` path); the
processor, storage and pipeline factories are replaced so nothing touches PostgreSQL.
"""

import uuid
from typing import Any, ClassVar

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.core.request_context import get_request_id
from app.services.task_dispatcher import TaskDispatchError
from app.workers import tasks
from app.workers.celery_app import RECONCILE_STALE_JOBS_TASK, celery_app, create_celery_app
from app.workers.dispatcher import CeleryDocumentTaskDispatcher
from app.workers.pipeline import TransientProcessingError
from app.workers.processing import RETRIES_EXHAUSTED_MESSAGE, JobOutcome


class _Retry(Exception):  # noqa: N818  (mirrors celery.exceptions.Retry)
    pass


class _FakeProcessor:
    instances: ClassVar[list["_FakeProcessor"]] = []
    behaviour: ClassVar[str] = "complete"
    mark_failed_raises: ClassVar[bool] = False

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.runs: list[dict[str, Any]] = []
        self.request_ids: list[str | None] = []
        self.failed: list[tuple[uuid.UUID, str]] = []
        _FakeProcessor.instances.append(self)

    def mark_failed(self, job_id: uuid.UUID, message: str) -> bool:
        if _FakeProcessor.mark_failed_raises:
            raise OperationalError("UPDATE", {}, Exception("database down"))
        self.failed.append((job_id, message))
        return True

    def run(self, *, job_id: uuid.UUID, is_final_attempt: bool) -> JobOutcome:
        self.runs.append({"job_id": job_id, "is_final_attempt": is_final_attempt})
        self.request_ids.append(get_request_id())
        if _FakeProcessor.behaviour == "transient":
            raise TransientProcessingError("OSError")
        return JobOutcome.COMPLETED


@pytest.fixture
def fake_processor(monkeypatch: pytest.MonkeyPatch) -> type[_FakeProcessor]:
    _FakeProcessor.instances = []
    _FakeProcessor.behaviour = "complete"
    _FakeProcessor.mark_failed_raises = False
    monkeypatch.setattr(tasks, "DocumentProcessor", _FakeProcessor)
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda _settings: object())
    monkeypatch.setattr(tasks, "build_indexing_pipeline", lambda **_kwargs: "pipeline")
    monkeypatch.setattr(tasks, "get_storage_service", lambda: "storage")
    monkeypatch.setattr(tasks, "get_session_factory", lambda: "factory")
    return _FakeProcessor


def test_task_runs_processor_with_bounded_attempts_and_timeout_mapping(
    fake_processor: type[_FakeProcessor],
) -> None:
    job_id = uuid.uuid4()
    result = tasks.process_document(
        document_id=str(uuid.uuid4()), job_id=str(job_id), request_id="upload-req-1234"
    )
    assert result == "completed"
    processor = fake_processor.instances[0]
    retries = get_settings().celery_task_max_retries
    assert processor.kwargs["max_attempts"] == retries + 1 + tasks.EXTRA_REDELIVERY_ATTEMPTS
    assert processor.kwargs["timeout_errors"] == (SoftTimeLimitExceeded,)
    assert processor.runs == [{"job_id": job_id, "is_final_attempt": retries == 0}]
    # Worker logs share the upload request id; the context is reset afterwards.
    assert processor.request_ids == ["upload-req-1234"]
    assert get_request_id() is None


def test_transient_failure_schedules_retry_with_exponential_backoff(
    fake_processor: type[_FakeProcessor], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_processor.behaviour = "transient"
    seen: dict[str, Any] = {}

    def fake_retry(*, exc: BaseException, countdown: int) -> _Retry:
        seen.update(exc=exc, countdown=countdown)
        return _Retry()

    monkeypatch.setattr(tasks.process_document, "retry", fake_retry)
    with pytest.raises(_Retry):
        tasks.process_document(document_id=str(uuid.uuid4()), job_id=str(uuid.uuid4()))
    assert isinstance(seen["exc"], TransientProcessingError)
    assert seen["countdown"] == get_settings().celery_retry_backoff_seconds  # 2**0


@pytest.mark.parametrize("db_still_down", [False, True])
def test_transient_failure_on_final_attempt_fails_the_job_instead_of_retrying(
    fake_processor: type[_FakeProcessor], monkeypatch: pytest.MonkeyPatch, db_still_down: bool
) -> None:
    """E.g. the last attempt could not write its result: no retry is left, so the job must
    become terminal now (or, if the database is still down, via the stale-job reconciler)."""
    fake_processor.behaviour = "transient"
    fake_processor.mark_failed_raises = db_still_down
    monkeypatch.setattr(tasks.process_document, "max_retries", 0)

    def no_retry(**_: Any) -> _Retry:
        raise AssertionError("must not retry after the final attempt")

    monkeypatch.setattr(tasks.process_document, "retry", no_retry)
    job_id = uuid.uuid4()
    result = tasks.process_document(document_id=str(uuid.uuid4()), job_id=str(job_id))
    assert result == "failed"
    processor = fake_processor.instances[0]
    assert processor.runs == [{"job_id": job_id, "is_final_attempt": True}]
    expected = [] if db_still_down else [(job_id, RETRIES_EXHAUSTED_MESSAGE)]
    assert processor.failed == expected


def test_reconciler_is_scheduled_on_beat_and_registered() -> None:
    schedule = create_celery_app().conf.beat_schedule
    entry = schedule["reconcile-stale-jobs"]
    assert entry["task"] == RECONCILE_STALE_JOBS_TASK
    assert entry["schedule"] == float(get_settings().stale_job_check_interval_seconds)
    assert RECONCILE_STALE_JOBS_TASK in celery_app.tasks


def test_reconciler_schedule_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    disabled = get_settings().model_copy(update={"stale_job_check_interval_seconds": 0})
    monkeypatch.setattr("app.workers.celery_app.get_settings", lambda: disabled)
    assert not create_celery_app().conf.beat_schedule


def test_max_claim_attempts() -> None:
    assert tasks.max_claim_attempts(3) == 6
    assert tasks.max_claim_attempts(0) == 3


def test_dispatcher_publishes_with_task_id_and_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        tasks.process_document, "apply_async", lambda **kwargs: calls.append(kwargs)
    )
    document_id, job_id = uuid.uuid4(), uuid.uuid4()
    CeleryDocumentTaskDispatcher().enqueue_processing(
        document_id=document_id, job_id=job_id, task_id="task-1"
    )
    assert calls[0]["task_id"] == "task-1"
    assert calls[0]["kwargs"]["document_id"] == str(document_id)
    assert calls[0]["kwargs"]["job_id"] == str(job_id)
    assert calls[0]["retry"] is True


def test_dispatcher_wraps_broker_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_: Any) -> None:
        raise ConnectionError("redis://:secret@host down")

    monkeypatch.setattr(tasks.process_document, "apply_async", boom)
    with pytest.raises(TaskDispatchError) as excinfo:
        CeleryDocumentTaskDispatcher().enqueue_processing(
            document_id=uuid.uuid4(), job_id=uuid.uuid4(), task_id="t"
        )
    assert "secret" not in str(excinfo.value)
