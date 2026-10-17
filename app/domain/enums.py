"""Domain enumerations shared by models, schemas, services and workers."""

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class DocumentStatus(StrEnum):
    """Lifecycle of an uploaded document.

    ``completed`` currently means "stored and verified by the worker". Content
    extraction, chunking and embedding are not implemented yet (planned for DIP2);
    they will run inside the ``processing`` state.
    """

    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditAction(StrEnum):
    USER_REGISTERED = "user.registered"
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_DELETED = "document.deleted"


class ResourceType(StrEnum):
    USER = "user"
    DOCUMENT = "document"
