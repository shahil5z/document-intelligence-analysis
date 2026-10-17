"""Boundary between the API and the task queue.

Services depend on this protocol rather than on Celery directly, so tests can
substitute a recording fake and the queue technology can change in one place.
"""

import uuid
from typing import Protocol


class TaskDispatchError(Exception):
    """Raised when a task could not be handed to the broker."""


class DocumentTaskDispatcher(Protocol):
    def enqueue_processing(
        self, *, document_id: uuid.UUID, job_id: uuid.UUID, task_id: str
    ) -> None: ...
