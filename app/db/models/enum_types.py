"""PostgreSQL ENUM column types that persist the enum *values* (lower-case strings)."""

from enum import Enum

from sqlalchemy import Enum as SAEnum

from app.domain.enums import DocumentStatus, JobStatus, UserRole


def _pg_enum(enum_cls: type[Enum], name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


user_role_enum = _pg_enum(UserRole, "user_role")
document_status_enum = _pg_enum(DocumentStatus, "document_status")
job_status_enum = _pg_enum(JobStatus, "job_status")
