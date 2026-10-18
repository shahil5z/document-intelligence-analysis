"""Celery application. Configuration comes from the same Settings as the API."""

from typing import Any

from celery import Celery
from celery.signals import setup_logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.storage.factory import check_storage_backend


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
        task_soft_time_limit=240,
        task_time_limit=300,
        result_expires=24 * 60 * 60,
        broker_connection_retry_on_startup=True,
        broker_connection_timeout=5,
        # Fail fast when publishing while Redis is unreachable so uploads are not held open.
        broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 5},
        redis_socket_connect_timeout=2,
        redis_socket_timeout=5,
        worker_hijack_root_logger=False,
    )
    return app


@setup_logging.connect
def _configure_worker_logging(**_: Any) -> None:
    configure_logging(get_settings().log_level)


celery_app = create_celery_app()
