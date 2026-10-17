"""Celery task definitions (thin adapters around ``DocumentProcessor``)."""

from __future__ import annotations

import logging
import uuid

from celery import Task

from app.core.config import get_settings
from app.core.request_context import RequestContext, bind_context, reset_context
from app.db.session import get_session_factory
from app.storage.factory import get_storage_service
from app.workers.celery_app import celery_app
from app.workers.pipeline import TransientProcessingError, build_default_pipeline
from app.workers.processing import DocumentProcessor

logger = logging.getLogger(__name__)

PROCESS_DOCUMENT_TASK = "documents.process"


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
        processor = DocumentProcessor(
            session_factory=get_session_factory(),
            storage=get_storage_service(),
            pipeline=build_default_pipeline(),
        )
        retries = int(self.request.retries or 0)
        try:
            outcome = processor.run(
                job_id=uuid.UUID(job_id), is_final_attempt=retries >= (self.max_retries or 0)
            )
        except TransientProcessingError as exc:
            countdown = get_settings().celery_retry_backoff_seconds * (2**retries)
            logger.warning("task.retrying", extra={"retry_in_seconds": countdown})
            raise self.retry(exc=exc, countdown=countdown) from exc
        return outcome.value
    finally:
        reset_context(token)
