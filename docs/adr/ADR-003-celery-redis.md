# ADR-003: Celery with Redis for background processing

**Status:** Accepted (DIP1)

## Context
Document processing (today an integrity check; in DIP2 extraction, chunking and
embedding) can take seconds to minutes and must not block upload requests. Jobs must
survive API restarts and be retryable.

## Decision
- **Celery** worker, **Redis** as broker. Task: `documents.process`
  (`app/workers/tasks.py`).
- The authoritative job state lives in PostgreSQL (`document_processing_jobs`), not in
  the Celery result backend; the task is declared `ignore_result=True`.
- The API generates the Celery `task_id`, stores it on the job, commits, and only then
  publishes, so a worker can never see a job that is not yet committed.
- `task_acks_late` + `task_reject_on_worker_lost` + `worker_prefetch_multiplier=1`: a
  crash re-delivers the task; the processor is idempotent (terminal jobs are skipped,
  the job row is locked with `SELECT ... FOR UPDATE`).
- Transient errors are retried with exponential backoff (`CELERY_TASK_MAX_RETRIES`,
  `CELERY_RETRY_BACKOFF_SECONDS`); permanent errors fail the job with a safe message.

## Alternatives
- **FastAPI BackgroundTasks**: in-process, lost on restart, no retries.
- **RQ / Dramatiq / arq**: simpler, but Celery has the widest operational knowledge and
  built-in retry/ack semantics; arq would require async DB code.
- **PostgreSQL-backed queue** (e.g. `SELECT ... SKIP LOCKED`): fewer services, but more
  custom code for scheduling and retries.

## Consequences
- Redis becomes a required dependency (checked by `/health/ready`).
- If the broker is unreachable at upload time the job is marked `failed` with a safe
  message (measured once on the dev box: the request returned after about 8 s with
  Redis stopped). Re-queueing is planned (state machine already allows `failed -> queued`).
- Celery is untyped; `celery-types` stubs are used for mypy.
