from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, Integer, String, false, text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enum_types import user_role_enum
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import UserRole

if TYPE_CHECKING:
    from app.db.models.document import Document


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_demo_expires_at", "demo_expires_at", postgresql_where=text("is_demo")),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        user_role_enum, nullable=False, default=UserRole.USER, server_default=UserRole.USER.value
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    # Demo mode (migration 0003): ephemeral accounts created by POST /auth/demo. They
    # cannot log in with a password, are limited by the counters below and are deleted
    # with their files after demo_expires_at.
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    demo_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demo_questions_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    demo_uploads_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"User(id={self.id}, role={self.role}, demo={self.is_demo})"
