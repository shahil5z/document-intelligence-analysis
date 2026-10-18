import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.api.dependencies.auth import CurrentUser, UploadUser
from app.api.dependencies.pagination import Pagination
from app.api.dependencies.rate_limit import limit_by_upload_user, limit_by_user
from app.api.dependencies.services import DocumentServiceDep
from app.api.dependencies.settings import AppSettings
from app.api.responses import error_responses
from app.schemas.common import Page
from app.schemas.document import (
    DocumentRead,
    DocumentStatusResponse,
    DocumentUploadResponse,
    ProcessingJobRead,
    UploadPolicy,
)
from app.services.document_service import IncomingFile

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
    description=(
        "Multipart upload of a single PDF, DOCX or TXT file (allow-list from configuration). "
        "The extension, declared content type and leading magic bytes are checked, the size "
        "limit is enforced while streaming to storage, and a processing job is queued. "
        "Uploading identical content twice returns 409. Accepts an access token or an "
        "upload-only token from `POST /auth/upload-token`."
    ),
    responses=error_responses(400, 401, 409, 413, 415, 422, 429),
    dependencies=[Depends(limit_by_upload_user("upload"))],
)
def upload_document(
    user: UploadUser,
    documents: DocumentServiceDep,
    file: Annotated[UploadFile, File(description="The document to upload.")],
) -> DocumentUploadResponse:
    result = documents.upload(
        owner=user,
        incoming=IncomingFile(
            filename=file.filename, content_type=file.content_type, stream=file.file
        ),
    )
    return DocumentUploadResponse(
        id=result.document.id,
        status=result.document.status,
        job_id=result.job.id,
        job_status=result.job.status,
    )


@router.get(
    "/upload-policy",
    response_model=UploadPolicy,
    summary="Upload limits",
    description="Size limit and allow-lists that POST /documents enforces, for client-side checks.",
    responses=error_responses(401),
)
def upload_policy(_user: CurrentUser, settings: AppSettings) -> UploadPolicy:
    return UploadPolicy(
        max_upload_size_bytes=settings.max_upload_size_bytes,
        allowed_extensions=list(settings.allowed_extensions),
        allowed_content_types=list(settings.allowed_content_types),
    )


@router.get(
    "",
    response_model=Page[DocumentRead],
    summary="List my documents",
    description="Newest first. Only the caller's own documents are returned.",
    responses=error_responses(401, 422),
)
def list_documents(
    user: CurrentUser, documents: DocumentServiceDep, pagination: Pagination
) -> Page[DocumentRead]:
    rows, total = documents.list_documents(
        owner=user, offset=pagination.offset, limit=pagination.page_size
    )
    return Page[DocumentRead](
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        items=[DocumentRead.model_validate(row) for row in rows],
    )


@router.get(
    "/{document_id}",
    response_model=DocumentRead,
    summary="Get document metadata",
    responses=error_responses(401, 404, 422),
)
def get_document(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> DocumentRead:
    return DocumentRead.model_validate(documents.get_document(owner=user, document_id=document_id))


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Get processing status",
    description="Document status plus the latest processing job. Errors are user-safe messages.",
    responses=error_responses(401, 404, 422),
)
def get_document_status(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> DocumentStatusResponse:
    view = documents.get_status(owner=user, document_id=document_id)
    return DocumentStatusResponse(
        document_id=view.document.id,
        status=view.document.status,
        job=ProcessingJobRead.model_validate(view.job) if view.job else None,
        chunk_count=view.chunk_count,
    )


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reprocess a document",
    description=(
        "Queue a new processing job for a `completed` or `failed` document (for example "
        "after a failed run or a chunking change). The document is not searchable until "
        "the new job completes. 409 while it is queued or processing."
    ),
    responses=error_responses(401, 404, 409, 422, 429),
    dependencies=[Depends(limit_by_user("reprocess"))],
)
def reprocess_document(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> DocumentUploadResponse:
    result = documents.reprocess(owner=user, document_id=document_id)
    return DocumentUploadResponse(
        id=result.document.id,
        status=result.document.status,
        job_id=result.job.id,
        job_status=result.job.status,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
    description="Deletes the record, its jobs, its indexed chunks and the stored file.",
    responses=error_responses(401, 404, 422),
)
def delete_document(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> Response:
    documents.delete_document(owner=user, document_id=document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
