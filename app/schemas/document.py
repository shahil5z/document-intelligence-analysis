import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import DocumentStatus, JobStatus


class DocumentRead(BaseModel):
    """Public view of a document. Storage keys and generated filenames are never exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str = Field(examples=["quarterly-report.pdf"])
    content_type: str = Field(examples=["application/pdf"])
    file_size: int = Field(description="Size in bytes.", examples=[48213])
    checksum_sha256: str
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    id: uuid.UUID
    status: DocumentStatus
    job_id: uuid.UUID
    job_status: JobStatus


class ProcessingJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: JobStatus
    attempts: int
    stage: str | None = Field(
        default=None,
        description="Last pipeline step started: integrity_check, extract, normalize, chunk, "
        "embed or index.",
    )
    error_message: str | None = Field(
        default=None, description="Safe, user-facing failure reason (no internal details)."
    )
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus
    job: ProcessingJobRead | None
    chunk_count: int = Field(default=0, description="Indexed chunks (searchable when completed).")
