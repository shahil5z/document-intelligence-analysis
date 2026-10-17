import uuid

from app.core.request_context import get_request_id
from app.services.task_dispatcher import TaskDispatchError
from app.workers.tasks import process_document

_PUBLISH_RETRY_POLICY = {
    "max_retries": 2,
    "interval_start": 0,
    "interval_step": 0.5,
    "interval_max": 1,
}


class CeleryDocumentTaskDispatcher:
    """Publishes processing tasks to the Celery broker."""

    def enqueue_processing(
        self, *, document_id: uuid.UUID, job_id: uuid.UUID, task_id: str
    ) -> None:
        try:
            process_document.apply_async(
                kwargs={
                    "document_id": str(document_id),
                    "job_id": str(job_id),
                    "request_id": get_request_id(),
                },
                task_id=task_id,
                retry=True,
                retry_policy=_PUBLISH_RETRY_POLICY,
            )
        except Exception as exc:
            raise TaskDispatchError("could not publish processing task") from exc
