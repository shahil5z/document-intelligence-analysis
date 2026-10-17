import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DocumentProcessingJob


class ProcessingJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: DocumentProcessingJob) -> DocumentProcessingJob:
        self._session.add(job)
        self._session.flush()
        return job

    def get(self, job_id: uuid.UUID) -> DocumentProcessingJob | None:
        return self._session.get(DocumentProcessingJob, job_id)

    def get_for_update(self, job_id: uuid.UUID) -> DocumentProcessingJob | None:
        """Row-lock the job so concurrent deliveries of the same task serialise."""
        return self._session.scalar(
            select(DocumentProcessingJob)
            .where(DocumentProcessingJob.id == job_id)
            .with_for_update()
        )

    def latest_for_document(self, document_id: uuid.UUID) -> DocumentProcessingJob | None:
        return self._session.scalar(
            select(DocumentProcessingJob)
            .where(DocumentProcessingJob.document_id == document_id)
            .order_by(DocumentProcessingJob.created_at.desc(), DocumentProcessingJob.id)
            .limit(1)
        )
