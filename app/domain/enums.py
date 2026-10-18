"""Domain enumerations shared by models, schemas, services and workers."""

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class DocumentStatus(StrEnum):
    """Lifecycle of an uploaded document.

    ``completed`` means the stored file was verified, its text extracted, normalized,
    chunked, embedded and indexed (DIP2): the document is searchable. All of that runs
    inside ``processing``; ``failed`` carries a safe reason on the job.
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
    DOCUMENT_REPROCESS_REQUESTED = "document.reprocess_requested"


class ResourceType(StrEnum):
    USER = "user"
    DOCUMENT = "document"


class SearchMode(StrEnum):
    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    HYBRID = "hybrid"
