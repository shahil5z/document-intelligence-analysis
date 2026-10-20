"""Celery task definitions (thin adapters around ``DocumentProcessor``)."""

from __future__ import annotations

import logging
import uuid

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import OperationalError

from app.ai.factory import (
    create_embedding_provider,
    create_suggestion_llm,
    create_token_counter,
)
from app.core.config import get_settings
from app.core.request_context import RequestContext, bind_context, reset_context
from app.db.session import get_session_factory
from app.services.demo_service import cleanup_expired_demo_users
from app.storage.factory import get_storage_service
from app.workers.celery_app import CLEANUP_DEMO_USERS_TASK, RECONCILE_STALE_JOBS_TASK, celery_app
from app.workers.pipeline import TransientProcessingError
from app.workers.processing import RETRIES_EXHAUSTED_MESSAGE, DocumentProcessor, JobOutcome
from app.workers.reconcile import reconcile_stale_jobs
from app.workers.steps import build_indexing_pipeline

logger = logging.getLogger(__name__)

PROCESS_DOCUMENT_TASK = "documents.process"
# Claims allowed beyond the normal retry budget, for redeliveries after a worker crash or
# a hard time limit kill (acks_late + reject_on_worker_lost). Then the job is failed.
EXTRA_REDELIVERY_ATTEMPTS = 2


def max_claim_attempts(max_retries: int) -> int:
    return max_retries + 1 + EXTRA_REDELIVERY_ATTEMPTS


def fail_after_retries(processor: DocumentProcessor, job_id: uuid.UUID) -> JobOutcome:
    """Terminal failure once the retry budget is spent (best effort).

    If even this write fails (database still down), the job is left to the stale-job
    reconciler, which fails it after STALE_JOB_TIMEOUT_SECONDS.
    """
    try:
        processor.mark_failed(job_id, RETRIES_EXHAUSTED_MESSAGE)
    except OperationalError:
        logger.error("job.terminal_state_not_persisted", extra={"job_id": str(job_id)})
    return JobOutcome.FAILED


@celery_app.task(
    bind=True,
    name=PROCESS_DOCUMENT_TASK,
    max_retries=get_settings().celery_task_max_retries,
    # Outcomes are persisted on the job row; not storing Celery results also means
    # publishing does not depend on the result backend being reachable.
    ignore_result=True,
)
def process_document(
    self: Task[..., str], document_id: str, job_id: str, request_id: str | None = None
) -> str:
    """Process one uploaded document. ``request_id`` links worker logs to the upload request."""
    token = bind_context(
        RequestContext(request_id=request_id or str(self.request.id), document_id=document_id)
    )
    try:
        settings = get_settings()
        # Cached per worker process; the model loads on the first embed call (or, with
        # EMBEDDING_PROVIDER=remote, embedding is delegated to the API).
        embedder = create_embedding_provider(settings)
        processor = DocumentProcessor(
            session_factory=get_session_factory(),
            storage=get_storage_service(),
            pipeline=build_indexing_pipeline(
                settings=settings,
                session_factory=get_session_factory(),
                embedder=embedder,
                # Tokenizer only: chunking never needs the model weights.
                token_counter=create_token_counter(settings),
                # One small HTTP call to the LLM; None when not configured.
                suggestion_llm=create_suggestion_llm(settings),
            ),
            max_attempts=max_claim_attempts(settings.celery_task_max_retries),
            timeout_errors=(SoftTimeLimitExceeded,),
        )
        retries = int(self.request.retries or 0)
        is_final_attempt = retries >= (self.max_retries or 0)
        try:
            outcome = processor.run(job_id=uuid.UUID(job_id), is_final_attempt=is_final_attempt)
        except TransientProcessingError as exc:
            if is_final_attempt:
                # No retry left (e.g. the final state could not be written): fail the job
                # now instead of leaving it "processing" forever.
                return fail_after_retries(processor, uuid.UUID(job_id)).value
            countdown = get_settings().celery_retry_backoff_seconds * (2**retries)
            logger.warning("task.retrying", extra={"retry_in_seconds": countdown})
            raise self.retry(exc=exc, countdown=countdown) from exc
        return outcome.value
    finally:
        reset_context(token)


@celery_app.task(name=RECONCILE_STALE_JOBS_TASK, ignore_result=True)
def reconcile_stale_jobs_task() -> int:
    """Periodic (beat) task: fail jobs stuck in processing/retrying (app/workers/reconcile.py)."""
    return reconcile_stale_jobs(
        get_session_factory(), timeout_seconds=get_settings().stale_job_timeout_seconds
    )


@celery_app.task(name=CLEANUP_DEMO_USERS_TASK, ignore_result=True)
def cleanup_expired_demo_users_task() -> int:
    """Periodic (beat) task: delete expired demo users and their files (demo_service)."""
    return cleanup_expired_demo_users(get_session_factory(), get_storage_service())
