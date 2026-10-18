import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import UUIDPrimaryKeyMixin

# Fixed by migration 0002. Changing the embedding model's dimension needs a new migration
# (and re-embedding every document); EMBEDDING_DIMENSION is checked against the model.
EMBEDDING_DIMENSION = 384
TEXT_SEARCH_CONFIG = "english"


class DocumentChunk(UUIDPrimaryKeyMixin, Base):
    """One retrievable passage of a document with its embedding and full-text vector.

    ``owner_id`` is denormalised from ``documents`` so every search query can filter by
    owner on the chunk table itself; chunks are removed with their document (CASCADE).
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        # Idempotency: re-indexing replaces chunks; a duplicate index is a bug, not data.
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_id"),
        Index("ix_document_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(f"to_tsvector('{TEXT_SEARCH_CONFIG}'::regconfig, content)", persisted=True),
        nullable=True,
    )
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"DocumentChunk(document_id={self.document_id}, index={self.chunk_index})"
