"""Document use cases: upload, list, read, status, delete.

Transaction boundaries live here. Ownership is enforced by the repository queries,
and documents owned by someone else surface as 404 (never 403) to avoid enumeration.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.core.request_context import set_document_id
from app.db.models import Document, DocumentProcessingJob, User
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.documents import DocumentRepository
from app.db.repositories.jobs import ProcessingJobRepository
from app.domain.enums import AuditAction, DocumentStatus, JobStatus, ResourceType
from app.domain.state_machine import transition_document, transition_job
from app.services.audit_service import AuditService
from app.services.task_dispatcher import DocumentTaskDispatcher
from app.services.upload_validation import (
    StreamDigest,
    normalize_content_type,
    sanitize_filename,
    validate_file_type,
    validated_chunks,
)
from app.storage.base import StorageService

logger = logging.getLogger(__name__)

DOCUMENT_NOT_FOUND = "Document not found"
ENQUEUE_FAILED_MESSAGE = (
    "Processing could not be scheduled. Reprocess the document or delete and upload it again."
)
REPROCESSABLE_STATUSES = frozenset({DocumentStatus.COMPLETED, DocumentStatus.FAILED})


@dataclass(frozen=True)
class IncomingFile:
    filename: str | None
    content_type: str | None
    stream: BinaryIO


@dataclass(frozen=True)
class UploadResult:
    document: Document
    job: DocumentProcessingJob


@dataclass(frozen=True)
class DocumentStatusView:
    document: Document
    job: DocumentProcessingJob | None
    chunk_count: int = 0


class DocumentService:
    def __init__(
        self,
        session: Session,
        storage: StorageService,
        dispatcher: DocumentTaskDispatcher,
        settings: Settings,
    ) -> None:
        self._session = session
        self._storage = storage
        self._dispatcher = dispatcher
        self._settings = settings
        self._documents = DocumentRepository(session)
        self._jobs = ProcessingJobRepository(session)
        self._audit = AuditService(session)

    def upload(self, *, owner: User, incoming: IncomingFile) -> UploadResult:
        original_filename = sanitize_filename(incoming.filename)
        content_type = normalize_content_type(incoming.content_type)
        extension = validate_file_type(
            filename=original_filename,
            content_type=content_type,
            allowed_extensions=self._settings.allowed_extensions,
            allowed_content_types=self._settings.allowed_content_types,
        )

        document_id = uuid.uuid4()
        generated_filename = f"{document_id.hex}.{extension}"
        storage_key = f"documents/{owner.id}/{generated_filename}"
        digest = StreamDigest()
        self._storage.save(
            storage_key,
            validated_chunks(
                incoming.stream,
                extension=extension,
                max_size=self._settings.max_upload_size_bytes,
                chunk_size=self._settings.upload_chunk_size_bytes,
                digest=digest,
            ),
        )

        try:
            result = self._persist_upload(
                owner=owner,
                document_id=document_id,
                generated_filename=generated_filename,
                original_filename=original_filename,
                content_type=content_type,
                storage_key=storage_key,
                digest=digest,
            )
        except Exception:
            self._session.rollback()
            self._storage.delete(storage_key)
            raise

        set_document_id(str(document_id))
        logger.info("document.uploaded", extra={"file_size": digest.size})
        self._enqueue(result)
        return result

    def _persist_upload(
        self,
        *,
        owner: User,
        document_id: uuid.UUID,
        generated_filename: str,
        original_filename: str,
        content_type: str,
        storage_key: str,
        digest: StreamDigest,
    ) -> UploadResult:
        if self._documents.get_by_checksum_for_owner(digest.hexdigest, owner.id) is not None:
            raise ConflictError("You have already uploaded a file with identical content")

        document = Document(
            id=document_id,
            owner_id=owner.id,
            filename=generated_filename,
            original_filename=original_filename,
            content_type=content_type,
            file_size=digest.size,
            storage_key=storage_key,
            checksum_sha256=digest.hexdigest,
            status=DocumentStatus.UPLOADED,
        )
        job = DocumentProcessingJob(
            document_id=document_id, status=JobStatus.PENDING, task_id=str(uuid.uuid4())
        )
        try:
            self._documents.add(document)
            self._jobs.add(job)
        except IntegrityError as exc:
            raise ConflictError("You have already uploaded a file with identical content") from exc

        # Mark as queued *before* committing so the worker never observes a pending job.
        transition_document(document, DocumentStatus.QUEUED)
        transition_job(job, JobStatus.QUEUED)
        self._audit.record(
            AuditAction.DOCUMENT_UPLOADED,
            user_id=owner.id,
            resource_type=ResourceType.DOCUMENT,
            resource_id=document.id,
            details={
                "original_filename": original_filename,
                "content_type": content_type,
                "file_size": digest.size,
            },
        )
        self._session.commit()
        return UploadResult(document=document, job=job)

    def _enqueue(self, result: UploadResult) -> None:
        job, document = result.job, result.document
        if job.task_id is None:
            raise RuntimeError("processing job has no task id")
        try:
            self._dispatcher.enqueue_processing(
                document_id=document.id, job_id=job.id, task_id=job.task_id
            )
        except Exception:
            logger.exception("document.enqueue_failed", extra={"job_id": str(job.id)})
            transition_job(job, JobStatus.FAILED)
            transition_document(document, DocumentStatus.FAILED)
            job.error_message = ENQUEUE_FAILED_MESSAGE
            self._session.commit()
            return
        logger.info("document.enqueued", extra={"job_id": str(job.id)})

    def list_documents(
        self, *, owner: User, offset: int, limit: int
    ) -> tuple[Sequence[Document], int]:
        return self._documents.list_for_owner(owner.id, offset=offset, limit=limit)

    def get_document(self, *, owner: User, document_id: uuid.UUID) -> Document:
        document = self._documents.get_for_owner(document_id, owner.id)
        if document is None:
            raise NotFoundError(DOCUMENT_NOT_FOUND)
        return document

    def get_status(self, *, owner: User, document_id: uuid.UUID) -> DocumentStatusView:
        document = self.get_document(owner=owner, document_id=document_id)
        return DocumentStatusView(
            document=document,
            job=self._jobs.latest_for_document(document.id),
            chunk_count=ChunkRepository(self._session).count_for_document(document.id),
        )

    def reprocess(self, *, owner: User, document_id: uuid.UUID) -> UploadResult:
        """Queue a new processing job for a completed or failed document.

        Existing chunks stay in place but are not searchable while the document is not
        ``completed``; the index step replaces them atomically.
        """
        document = self.get_document(owner=owner, document_id=document_id)
        if document.status not in REPROCESSABLE_STATUSES:
            raise ConflictError("The document is already queued or being processed")
        job = DocumentProcessingJob(
            document_id=document.id, status=JobStatus.PENDING, task_id=str(uuid.uuid4())
        )
        self._jobs.add(job)
        transition_document(document, DocumentStatus.QUEUED)
        transition_job(job, JobStatus.QUEUED)
        self._audit.record(
            AuditAction.DOCUMENT_REPROCESS_REQUESTED,
            user_id=owner.id,
            resource_type=ResourceType.DOCUMENT,
            resource_id=document.id,
        )
        self._session.commit()
        result = UploadResult(document=document, job=job)
        self._enqueue(result)
        return result

    def delete_document(self, *, owner: User, document_id: uuid.UUID) -> None:
        document = self.get_document(owner=owner, document_id=document_id)
        storage_key = document.storage_key
        self._audit.record(
            AuditAction.DOCUMENT_DELETED,
            user_id=owner.id,
            resource_type=ResourceType.DOCUMENT,
            resource_id=document.id,
            details={"original_filename": document.original_filename},
        )
        self._documents.delete(document)
        self._session.commit()
        # The record is gone first: an orphaned file is recoverable, a record pointing
        # at a missing file is a user-visible inconsistency.
        try:
            self._storage.delete(storage_key)
        except Exception:
            logger.exception(
                "document.storage_delete_failed", extra={"document_id": str(document_id)}
            )
        logger.info("document.deleted", extra={"document_id": str(document_id)})
