"""Initial schema: users, documents, processing jobs, audit logs; enable pgvector.

Revision ID: 0001
Revises:
Create Date: 2026-10-17

Hand-written and checked against the ORM models with ``alembic check``.
The ``vector`` extension is enabled so DIP2 can add embedding columns in a later
migration; no vector columns exist yet.
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM("user", "admin", name="user_role", create_type=False)
document_status = postgresql.ENUM(
    "uploaded",
    "queued",
    "processing",
    "completed",
    "failed",
    name="document_status",
    create_type=False,
)
job_status = postgresql.ENUM(
    "pending",
    "queued",
    "processing",
    "retrying",
    "completed",
    "failed",
    name="job_status",
    create_type=False,
)


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    document_status.create(bind, checkfirst=True)
    job_status.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, server_default="user", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("status", document_status, server_default="uploaded", nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_documents_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("owner_id", "checksum_sha256", name="uq_documents_owner_id_checksum"),
        sa.UniqueConstraint("storage_key", name=op.f("uq_documents_storage_key")),
    )
    op.create_index(op.f("ix_documents_owner_id"), "documents", ["owner_id"])
    op.create_index(op.f("ix_documents_status"), "documents", ["status"])
    op.create_index("ix_documents_owner_id_created_at", "documents", ["owner_id", "created_at"])

    op.create_table(
        "document_processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("status", job_status, server_default="pending", nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_processing_jobs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_processing_jobs")),
    )
    op.create_index(
        op.f("ix_document_processing_jobs_document_id"),
        "document_processing_jobs",
        ["document_id"],
    )
    op.create_index(
        op.f("ix_document_processing_jobs_status"), "document_processing_jobs", ["status"]
    )
    op.create_index(
        op.f("ix_document_processing_jobs_task_id"), "document_processing_jobs", ["task_id"]
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"])
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("document_processing_jobs")
    op.drop_table("documents")
    op.drop_table("users")
    bind = op.get_bind()
    job_status.drop(bind, checkfirst=True)
    document_status.drop(bind, checkfirst=True)
    user_role.drop(bind, checkfirst=True)
    # The vector extension is left in place: other database objects may depend on it.
