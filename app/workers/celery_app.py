"""Celery application. Configuration comes from the same Settings as the API."""

import logging
import os
from typing import Any

from celery import Celery
from celery.signals import setup_logging, worker_process_shutdown, worker_ready

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.storage.factory import check_storage_backend

logger = logging.getLogger(__name__)

RECONCILE_STALE_JOBS_TASK = "jobs.reconcile_stale"


def create_celery_app() -> Celery:
    settings = get_settings()
    check_storage_backend(settings)
    app = Celery(
        "document_intelligence_platform",
        broker=settings.get_celery_broker_url(),
        backend=settings.get_celery_result_backend(),
        include=["app.workers.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        # Re-deliver a task if the worker dies mid-way; the processor is idempotent.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_soft_time_limit=settings.celery_task_soft_time_limit,
        task_time_limit=settings.celery_task_time_limit,
        result_expires=24 * 60 * 60,
        broker_connection_retry_on_startup=True,
        broker_connection_timeout=5,
        # Fail fast when publishing while Redis is unreachable so uploads are not held open.
        broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 5},
        redis_socket_connect_timeout=2,
        redis_socket_timeout=5,
        worker_hijack_root_logger=False,
    )
    if settings.stale_job_check_interval_seconds > 0:
        # Executed by the embedded beat of the compose worker (`celery worker -B`).
        app.conf.beat_schedule = {
            "reconcile-stale-jobs": {
                "task": RECONCILE_STALE_JOBS_TASK,
                "schedule": float(settings.stale_job_check_interval_seconds),
                "options": {"expires": float(settings.stale_job_check_interval_seconds)},
            }
        }
    return app


@setup_logging.connect
def _configure_worker_logging(**_: Any) -> None:
    configure_logging(get_settings().log_level)


@worker_ready.connect
def _start_metrics_exporter(**_: Any) -> None:
    """Serve worker metrics on WORKER_METRICS_PORT (main worker process only)."""
    port = get_settings().worker_metrics_port
    if port is None:
        return
    from prometheus_client import start_http_server  # noqa: PLC0415

    from app.core.metrics import build_registry  # noqa: PLC0415

    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        logger.warning("worker.metrics_without_multiproc_dir")
    start_http_server(port, registry=build_registry())
    logger.info("worker.metrics_exporter_started", extra={"port": port})


@worker_process_shutdown.connect
def _mark_metrics_process_dead(pid: int | None = None, **_: Any) -> None:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess  # noqa: PLC0415

        multiprocess.mark_process_dead(pid or os.getpid())  # type: ignore[no-untyped-call]


celery_app = create_celery_app()
