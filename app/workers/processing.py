"""Framework-independent job execution used by the Celery task (and directly by tests)."""

import logging
import time
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.metrics import JOB_DURATION, JOBS
from app.db.models import Document, DocumentProcessingJob
from app.db.repositories.documents import DocumentRepository
from app.db.repositories.jobs import ProcessingJobRepository
from app.db.session import session_scope
from app.domain.enums import DocumentStatus, JobStatus
from app.domain.state_machine import TERMINAL_JOB_STATUSES, transition_document, transition_job
from app.storage.base import StorageError, StorageService
from app.workers.pipeline import (
    DocumentPipeline,
    PermanentProcessingError,
    PipelineContext,
    TransientProcessingError,
)

logger = logging.getLogger(__name__)

RETRIES_EXHAUSTED_MESSAGE = "Processing failed after several attempts"
UNEXPECTED_ERROR_MESSAGE = "Processing failed due to an internal error"
TIMEOUT_MESSAGE = "Processing took too long and was stopped"


class JobOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DocumentProcessor:
    """Runs one attempt of a processing job.

    ``max_attempts`` bounds how often a job may be *claimed* (normal retries plus
    redeliveries after worker crashes or hard time limits); beyond it the job is failed
    instead of being redelivered forever. ``timeout_errors`` are exception types raised
    by the task runner on a soft time limit (Celery's ``SoftTimeLimitExceeded``); they
    fail the job with a clear message instead of "internal error".
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: StorageService,
        pipeline: DocumentPipeline,
        *,
        max_attempts: int | None = None,
        timeout_errors: tuple[type[BaseException], ...] = (),
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._pipeline = pipeline
        self._max_attempts = max_attempts
        self._timeout_errors = timeout_errors

    def run(self, *, job_id: uuid.UUID, is_final_attempt: bool) -> JobOutcome:
        """Execute one attempt.

        Raises ``TransientProcessingError`` when the caller should retry (including when
        the final job state could not be written); every other failure is recorded on
        the job and reported as ``JobOutcome.FAILED``.
        """
        started = time.perf_counter()
        try:
            outcome = self._run(job_id=job_id, is_final_attempt=is_final_attempt)
        except TransientProcessingError:
            JOBS.labels("retry").inc()
            raise
        finally:
            JOB_DURATION.observe(time.perf_counter() - started)
        JOBS.labels(outcome.value).inc()
        return outcome

    def _run(self, *, job_id: uuid.UUID, is_final_attempt: bool) -> JobOutcome:
        try:
            context = self._claim(job_id)
        except OperationalError as exc:
            raise TransientProcessingError("database unavailable while claiming job") from exc
        if context is None:
            return JobOutcome.SKIPPED

        try:
            self._pipeline.run(context, on_step=lambda name: self._record_stage(job_id, name))
        except PermanentProcessingError as exc:
            logger.warning("job.failed", extra={"job_id": str(job_id), "reason": exc.safe_message})
            self._finish(job_id, JobStatus.FAILED, exc.safe_message)
            return JobOutcome.FAILED
        except (TransientProcessingError, StorageError, OSError, OperationalError) as exc:
            if is_final_attempt:
                logger.exception("job.retries_exhausted", extra={"job_id": str(job_id)})
                self._finish(job_id, JobStatus.FAILED, RETRIES_EXHAUSTED_MESSAGE)
                return JobOutcome.FAILED
            logger.warning("job.retry_scheduled", extra={"job_id": str(job_id)})
            self._mark_retrying(job_id)
            raise TransientProcessingError(type(exc).__name__) from exc
        except Exception as exc:
            if self._timeout_errors and isinstance(exc, self._timeout_errors):
                logger.warning("job.timed_out", extra={"job_id": str(job_id)})
                self._finish(job_id, JobStatus.FAILED, TIMEOUT_MESSAGE)
                return JobOutcome.FAILED
            logger.exception("job.unexpected_error", extra={"job_id": str(job_id)})
            self._finish(job_id, JobStatus.FAILED, UNEXPECTED_ERROR_MESSAGE)
            return JobOutcome.FAILED

        self._finish(job_id, JobStatus.COMPLETED, None)
        logger.info(
            "job.completed", extra={"job_id": str(job_id), "steps": self._pipeline.step_names}
        )
        return JobOutcome.COMPLETED

    def _claim(self, job_id: uuid.UUID) -> PipelineContext | None:
        with session_scope(self._session_factory) as session:
            job = ProcessingJobRepository(session).get_for_update(job_id)
            if job is None:
                logger.info("job.skipped_missing", extra={"job_id": str(job_id)})
                return None
            if job.status in TERMINAL_JOB_STATUSES:
                logger.info("job.skipped_terminal", extra={"job_id": str(job_id)})
                return None
            document = DocumentRepository(session).get_unscoped(job.document_id)
            if document is None:
                return None
            if self._max_attempts is not None and job.attempts >= self._max_attempts:
                # Redelivered again after crashes / hard time limits: stop the loop.
                logger.error(
                    "job.max_attempts_exceeded",
                    extra={"job_id": str(job_id), "attempts": job.attempts},
                )
                if job.status is not JobStatus.PROCESSING:
                    transition_job(job, JobStatus.PROCESSING)
                transition_job(job, JobStatus.FAILED)
                job.completed_at = datetime.now(UTC)
                job.error_message = RETRIES_EXHAUSTED_MESSAGE
                if document.status is not DocumentStatus.PROCESSING:
                    transition_document(document, DocumentStatus.PROCESSING)
                transition_document(document, DocumentStatus.FAILED)
                session.commit()
                return None
            if job.status is JobStatus.PROCESSING:
                # Redelivery after a worker crash (acks_late) or an unpersisted retry state.
                logger.warning("job.reclaimed", extra={"job_id": str(job_id)})
            else:
                transition_job(job, JobStatus.PROCESSING)
            if document.status is not DocumentStatus.PROCESSING:
                transition_document(document, DocumentStatus.PROCESSING)
            job.attempts += 1
            job.started_at = datetime.now(UTC)
            job.error_message = None
            context = PipelineContext(
                document_id=document.id,
                owner_id=document.owner_id,
                storage_key=document.storage_key,
                content_type=document.content_type,
                file_size=document.file_size,
                checksum_sha256=document.checksum_sha256,
                storage=self._storage,
            )
            session.commit()
            logger.info("job.started", extra={"job_id": str(job_id), "attempt": job.attempts})
            return context

    def _record_stage(self, job_id: uuid.UUID, stage: str) -> None:
        """Persist the current step in its own short transaction (best effort)."""
        try:
            with session_scope(self._session_factory) as session:
                session.execute(
                    update(DocumentProcessingJob)
                    .where(DocumentProcessingJob.id == job_id)
                    .values(stage=stage)
                )
                session.commit()
        except OperationalError:
            logger.warning("job.stage_not_persisted", extra={"job_id": str(job_id)})
        logger.info("job.stage", extra={"job_id": str(job_id), "stage": stage})

    def _load(
        self, session: Session, job_id: uuid.UUID
    ) -> tuple[DocumentProcessingJob, Document] | None:
        job = ProcessingJobRepository(session).get_for_update(job_id)
        if job is None:
            return None
        document = DocumentRepository(session).get_unscoped(job.document_id)
        if document is None:
            return None
        return job, document

    def _finish(self, job_id: uuid.UUID, status: JobStatus, error_message: str | None) -> None:
        """Write the final state. A database outage here becomes a retry (the redelivered
        attempt reclaims the ``processing`` job and re-runs the idempotent pipeline)
        instead of an unhandled error that would leave the job ``processing`` forever."""
        try:
            with session_scope(self._session_factory) as session:
                loaded = self._load(session, job_id)
                if loaded is None:
                    # The document was deleted while processing; nothing left to update.
                    return
                job, document = loaded
                if job.status in TERMINAL_JOB_STATUSES:
                    logger.warning("job.already_finished", extra={"job_id": str(job_id)})
                    return
                transition_job(job, status)
                job.completed_at = datetime.now(UTC)
                job.error_message = error_message
                transition_document(
                    document,
                    DocumentStatus.COMPLETED
                    if status is JobStatus.COMPLETED
                    else DocumentStatus.FAILED,
                )
                session.commit()
        except OperationalError as exc:
            logger.warning("job.finish_not_persisted", extra={"job_id": str(job_id)})
            raise TransientProcessingError("database unavailable while finishing job") from exc

    def _mark_retrying(self, job_id: uuid.UUID) -> None:
        try:
            with session_scope(self._session_factory) as session:
                loaded = self._load(session, job_id)
                if loaded is None:
                    return
                job, document = loaded
                transition_job(job, JobStatus.RETRYING)
                transition_document(document, DocumentStatus.QUEUED)
                session.commit()
        except OperationalError:
            logger.warning("job.retry_state_not_persisted", extra={"job_id": str(job_id)})
