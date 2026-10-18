"""Demo mode: ephemeral demo accounts with server-side usage counters.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18

- ``users.is_demo``: created by ``POST /auth/demo``; no password login.
- ``users.demo_expires_at``: when the cleanup beat task deletes the account and files.
- ``users.demo_questions_used`` / ``users.demo_uploads_used``: persistent counters the
  API checks and increments atomically (limits DEMO_MAX_QUESTIONS / DEMO_MAX_UPLOADS).
- Partial index on ``demo_expires_at`` for demo rows only (the cleanup query).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("demo_expires_at", sa.DateTime(timezone=True)))
    op.add_column(
        "users",
        sa.Column("demo_questions_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("demo_uploads_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_users_demo_expires_at",
        "users",
        ["demo_expires_at"],
        postgresql_where=sa.text("is_demo"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_demo_expires_at", table_name="users")
    op.drop_column("users", "demo_uploads_used")
    op.drop_column("users", "demo_questions_used")
    op.drop_column("users", "demo_expires_at")
    op.drop_column("users", "is_demo")
