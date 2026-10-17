import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enum_types import document_status_enum
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import DocumentStatus

if TYPE_CHECKING:
    from app.db.models.processing_job import DocumentProcessingJob
    from app.db.models.user import User


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        # One copy of identical content per user: duplicate uploads return 409.
        UniqueConstraint("owner_id", "checksum_sha256", name="uq_documents_owner_id_checksum"),
        Index("ix_documents_owner_id_created_at", "owner_id", "created_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        document_status_enum,
        nullable=False,
        default=DocumentStatus.UPLOADED,
        server_default=DocumentStatus.UPLOADED.value,
        index=True,
    )
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    owner: Mapped["User"] = relationship(back_populates="documents")
    jobs: Mapped[list["DocumentProcessingJob"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentProcessingJob.created_at",
    )

    def __repr__(self) -> str:
        return f"Document(id={self.id}, status={self.status})"
