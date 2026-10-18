"""Stale-job reconciliation: fail jobs that can no longer finish on their own.

A job can be left ``processing`` or ``retrying`` when the worker that owned it died after
its last allowed attempt (hard time limit, OOM kill, container stop) or when the final
state could not be written (database outage on the last retry). Nothing would ever move
such a job again, so it is failed here with a fixed, safe message once it is older than
``STALE_JOB_TIMEOUT_SECONDS``:

* ``processing``: ``started_at`` (set on every claim) is older than the timeout;
* ``retrying``: the row was last updated (retry scheduled) longer ago than the timeout.

The timeout must exceed ``CELERY_TASK_TIME_LIMIT`` (enforced in settings), so a job that
is still running is never touched. Rows are locked with ``FOR UPDATE SKIP LOCKED``: a job
currently being claimed or finished by a worker is skipped, and several reconcilers
(one embedded beat per worker container) can run concurrently without conflicts.

Runs every ``STALE_JOB_CHECK_INTERVAL_SECONDS`` via Celery beat (``jobs.reconcile_stale``,
the compose worker starts with ``-B``) and on demand with
``python -m app.cli reconcile-stale-jobs``.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.metrics import JOBS
from app.db.models import Document, DocumentProcessingJob
from app.db.session import session_scope
from app.domain.enums import JobStatus
from app.workers.processing import STALE_JOB_MESSAGE, force_fail

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100


def reconcile_stale_jobs(
    session_factory: sessionmaker[Session],
    *,
    timeout_seconds: int,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Fail stale ``processing``/``retrying`` jobs; return how many were failed."""
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=timeout_seconds)
    failed = 0
    with session_scope(session_factory) as session:
        jobs = session.scalars(
            select(DocumentProcessingJob)
            .where(
                or_(
                    and_(
                        DocumentProcessingJob.status == JobStatus.PROCESSING,
                        DocumentProcessingJob.started_at < cutoff,
                    ),
                    and_(
                        DocumentProcessingJob.status == JobStatus.RETRYING,
                        DocumentProcessingJob.updated_at < cutoff,
                    ),
                )
            )
            .order_by(DocumentProcessingJob.created_at, DocumentProcessingJob.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            # The FK guarantees the document exists; None means another transaction holds
            # it (indexing or deletion), so leave this job for the next run.
            document = session.scalar(
                select(Document)
                .where(Document.id == job.document_id)
                .with_for_update(skip_locked=True)
            )
            if document is None:
                continue
            previous = job.status
            if force_fail(job, document, STALE_JOB_MESSAGE):
                failed += 1
                JOBS.labels("stale_failed").inc()
                logger.warning(
                    "job.stale_failed",
                    extra={
                        "job_id": str(job.id),
                        "document_id": str(job.document_id),
                        "previous_status": previous.value,
                        "stage": job.stage,
                    },
                )
        session.commit()
    if failed:
        logger.info("jobs.reconciled", extra={"failed": failed})
    return failed
