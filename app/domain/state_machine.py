"""Allowed status transitions for documents and processing jobs.

All status changes go through :func:`transition_document` / :func:`transition_job`
so that illegal transitions fail loudly instead of silently corrupting state.
"""

from collections.abc import Mapping
from typing import Protocol

from app.domain.enums import DocumentStatus, JobStatus

DOCUMENT_TRANSITIONS: Mapping[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.UPLOADED: frozenset({DocumentStatus.QUEUED, DocumentStatus.FAILED}),
    DocumentStatus.QUEUED: frozenset({DocumentStatus.PROCESSING, DocumentStatus.FAILED}),
    DocumentStatus.PROCESSING: frozenset(
        {DocumentStatus.COMPLETED, DocumentStatus.FAILED, DocumentStatus.QUEUED}
    ),
    DocumentStatus.COMPLETED: frozenset({DocumentStatus.QUEUED}),
    DocumentStatus.FAILED: frozenset({DocumentStatus.QUEUED}),
}

JOB_TRANSITIONS: Mapping[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.QUEUED, JobStatus.FAILED}),
    JobStatus.QUEUED: frozenset({JobStatus.PROCESSING, JobStatus.FAILED}),
    JobStatus.PROCESSING: frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.RETRYING}),
    JobStatus.RETRYING: frozenset({JobStatus.PROCESSING, JobStatus.FAILED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
}

TERMINAL_JOB_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED})


class InvalidTransitionError(Exception):
    def __init__(self, entity: str, current: str, target: str) -> None:
        super().__init__(f"Illegal {entity} status transition: {current} -> {target}")
        self.current = current
        self.target = target


class _HasDocumentStatus(Protocol):
    status: DocumentStatus


class _HasJobStatus(Protocol):
    status: JobStatus


def can_transition_document(current: DocumentStatus, target: DocumentStatus) -> bool:
    return target in DOCUMENT_TRANSITIONS[current]


def can_transition_job(current: JobStatus, target: JobStatus) -> bool:
    return target in JOB_TRANSITIONS[current]


def transition_document(document: _HasDocumentStatus, target: DocumentStatus) -> None:
    if not can_transition_document(document.status, target):
        raise InvalidTransitionError("document", document.status, target)
    document.status = target


def transition_job(job: _HasJobStatus, target: JobStatus) -> None:
    if not can_transition_job(job.status, target):
        raise InvalidTransitionError("job", job.status, target)
    job.status = target
