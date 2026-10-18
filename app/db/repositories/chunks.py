"""Chunk persistence and retrieval queries.

Every search query filters in SQL by ``owner_id`` on the chunk row *and* joins the
parent document requiring the same owner and ``status = 'completed'``. Documents that
are being (re)processed, failed or deleted (rows removed, chunks cascade) are therefore
never searchable. Ties are broken by chunk id so result order is deterministic.
"""

import logging
import re
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    Float,
    Select,
    Text,
    cast,
    delete,
    func,
    insert,
    literal,
    literal_column,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnClause, ColumnElement

from app.db.models import Document, DocumentChunk
from app.db.models.document_chunk import TEXT_SEARCH_CONFIG
from app.domain.enums import DocumentStatus

logger = logging.getLogger(__name__)

_REGCONFIG: ColumnClause[Any] = literal_column(f"'{TEXT_SEARCH_CONFIG}'::regconfig")

# hnsw.iterative_scan exists from pgvector 0.8.0. On older versions PostgreSQL rejects the
# parameter ("hnsw" is a reserved prefix), so it is only set when supported; the result
# is cached per database URL (password hidden) for the life of the process.
ITERATIVE_SCAN_MIN_VERSION = (0, 8, 0)
# Minimum supported pgvector: HNSW indexes (migration 0002) exist from 0.5.0. Below 0.8.0
# filtered semantic searches may return fewer than top_k rows (no iterative scan); the
# readiness probe reports versions below 0.5.0 (or a missing extension) as an error.
PGVECTOR_MIN_VERSION = (0, 5, 0)
_iterative_scan_support: dict[str, bool] = {}
_support_lock = threading.Lock()


def parse_extension_version(version: str | None) -> tuple[int, ...]:
    """``"0.8.0"`` -> ``(0, 8, 0)``; unknown or missing -> ``()``."""
    if not version:
        return ()
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])


def supports_iterative_scan(version: str | None) -> bool:
    parsed = parse_extension_version(version)
    return bool(parsed) and parsed >= ITERATIVE_SCAN_MIN_VERSION


@dataclass(frozen=True)
class NewChunk:
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    token_count: int
    embedding: list[float]


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    token_count: int
    similarity: float | None
    keyword_score: float | None


class ChunkRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- writes (worker) -------------------------------------------------------------

    def replace_for_document(
        self,
        *,
        document_id: uuid.UUID,
        owner_id: uuid.UUID,
        chunks: Sequence[NewChunk],
        embedding_model: str,
    ) -> None:
        """Delete then insert all chunks of a document (caller commits once)."""
        self._session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        if not chunks:
            return
        self._session.execute(
            insert(DocumentChunk),
            [
                {
                    "id": uuid.uuid4(),
                    "document_id": document_id,
                    "owner_id": owner_id,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "token_count": chunk.token_count,
                    "embedding": chunk.embedding,
                    "embedding_model": embedding_model,
                }
                for chunk in chunks
            ],
        )

    def count_for_document(self, document_id: uuid.UUID) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
            )
            or 0
        )

    # --- reads (API) -----------------------------------------------------------------

    def _base(
        self, owner_id: uuid.UUID, document_id: uuid.UUID | None, *columns: ColumnElement[Any]
    ) -> Select[*tuple[Any, ...]]:
        query = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                Document.original_filename,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                DocumentChunk.page_start,
                DocumentChunk.page_end,
                DocumentChunk.char_start,
                DocumentChunk.char_end,
                DocumentChunk.token_count,
                *columns,
            )
            .join(
                Document,
                (Document.id == DocumentChunk.document_id)
                & (Document.owner_id == DocumentChunk.owner_id),
            )
            .where(
                DocumentChunk.owner_id == owner_id,
                Document.owner_id == owner_id,
                Document.status == DocumentStatus.COMPLETED,
            )
        )
        if document_id is not None:
            query = query.where(DocumentChunk.document_id == document_id)
        return query

    def semantic_search(
        self,
        *,
        owner_id: uuid.UUID,
        query_embedding: Sequence[float],
        limit: int,
        document_id: uuid.UUID | None = None,
    ) -> list[ChunkHit]:
        distance = DocumentChunk.embedding.cosine_distance(list(query_embedding))
        # Filtered HNSW scans can return fewer rows than LIMIT; iterative scans
        # (pgvector >= 0.8) keep scanning until enough rows pass the filters.
        if self._iterative_scan_available():
            self._session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        self._session.execute(
            text("SELECT set_config('hnsw.ef_search', :value, true)"),
            {"value": str(max(40, limit * 2))},
        )
        query = (
            self._base(
                owner_id,
                document_id,
                (literal(1.0) - distance).label("similarity"),
                cast(literal(None), Float).label("keyword_score"),
            )
            .order_by(distance, DocumentChunk.id)
            .limit(limit)
        )
        return [_to_hit(row) for row in self._session.execute(query)]

    def _iterative_scan_available(self) -> bool:
        bind = self._session.get_bind()
        key = bind.engine.url.render_as_string(hide_password=True)
        cached = _iterative_scan_support.get(key)
        if cached is not None:
            return cached
        version = self._session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        supported = supports_iterative_scan(version)
        with _support_lock:
            _iterative_scan_support[key] = supported
        if not supported:
            logger.warning(
                "search.pgvector_iterative_scan_unsupported",
                extra={"pgvector_version": version, "required": "0.8.0"},
            )
        return supported

    def keyword_search(
        self,
        *,
        owner_id: uuid.UUID,
        query_text: str,
        limit: int,
        document_id: uuid.UUID | None = None,
        query_embedding: Sequence[float] | None = None,
    ) -> list[ChunkHit]:
        """Full-text search ranked by ``ts_rank``; terms are OR-ed (see docs/retrieval.md).

        When ``query_embedding`` is given, each hit also carries its cosine similarity so
        callers (``/ask``) can apply the evidence threshold to keyword-only hits.
        """
        plain = func.plainto_tsquery(_REGCONFIG, query_text)
        tsquery = cast(func.replace(cast(plain, Text), " & ", " | "), TSQUERY)
        rank = func.ts_rank(DocumentChunk.content_tsv, tsquery, 1)
        similarity = (
            (literal(1.0) - DocumentChunk.embedding.cosine_distance(list(query_embedding)))
            if query_embedding is not None
            else cast(literal(None), Float)
        )
        query = (
            self._base(owner_id, document_id, similarity.label("similarity"), rank.label("rank"))
            .where(DocumentChunk.content_tsv.op("@@")(tsquery))
            .order_by(rank.desc(), DocumentChunk.id)
            .limit(limit)
        )
        return [_to_hit(row) for row in self._session.execute(query)]


def _to_hit(row: Row[Any]) -> ChunkHit:
    values = tuple(row)
    return ChunkHit(
        chunk_id=values[0],
        document_id=values[1],
        filename=values[2],
        chunk_index=values[3],
        content=values[4],
        page_start=values[5],
        page_end=values[6],
        char_start=values[7],
        char_end=values[8],
        token_count=values[9],
        similarity=None if values[10] is None else float(values[10]),
        keyword_score=None if values[11] is None else float(values[11]),
    )
