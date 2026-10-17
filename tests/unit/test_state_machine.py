from dataclasses import dataclass

import pytest

from app.domain.enums import DocumentStatus, JobStatus
from app.domain.state_machine import (
    DOCUMENT_TRANSITIONS,
    JOB_TRANSITIONS,
    InvalidTransitionError,
    transition_document,
    transition_job,
)


@dataclass
class _Doc:
    status: DocumentStatus


@dataclass
class _Job:
    status: JobStatus


def test_every_status_has_a_transition_entry() -> None:
    assert set(DOCUMENT_TRANSITIONS) == set(DocumentStatus)
    assert set(JOB_TRANSITIONS) == set(JobStatus)


def test_happy_path_document_lifecycle() -> None:
    doc = _Doc(DocumentStatus.UPLOADED)
    for target in (DocumentStatus.QUEUED, DocumentStatus.PROCESSING, DocumentStatus.COMPLETED):
        transition_document(doc, target)
    assert doc.status is DocumentStatus.COMPLETED


def test_illegal_transitions_raise() -> None:
    with pytest.raises(InvalidTransitionError):
        transition_document(_Doc(DocumentStatus.UPLOADED), DocumentStatus.COMPLETED)
    with pytest.raises(InvalidTransitionError):
        transition_job(_Job(JobStatus.COMPLETED), JobStatus.PROCESSING)


def test_job_retry_path() -> None:
    job = _Job(JobStatus.QUEUED)
    for target in (
        JobStatus.PROCESSING,
        JobStatus.RETRYING,
        JobStatus.PROCESSING,
        JobStatus.FAILED,
    ):
        transition_job(job, target)
    assert job.status is JobStatus.FAILED
