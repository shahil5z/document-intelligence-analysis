import uuid
from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile, status

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.pagination import Pagination
from app.api.dependencies.services import DocumentServiceDep
from app.api.responses import error_responses
from app.schemas.common import Page
from app.schemas.document import (
    DocumentRead,
    DocumentStatusResponse,
    DocumentUploadResponse,
    ProcessingJobRead,
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
        "Uploading identical content twice returns 409."
    ),
    responses=error_responses(400, 401, 409, 413, 415, 422),
)
def upload_document(
    user: CurrentUser,
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
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
    description="Deletes the record, its jobs and the stored file.",
    responses=error_responses(401, 404, 422),
)
def delete_document(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> Response:
    documents.delete_document(owner=user, document_id=document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
