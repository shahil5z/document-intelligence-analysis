"""Semantic, keyword and hybrid retrieval over the caller's completed documents."""

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.base import EmbeddingProvider, Reranker
from app.ai.errors import AIProviderConfigurationError, EmbeddingError
from app.core.config import Settings
from app.core.errors import InvalidQueryError, NotFoundError, ServiceUnavailableError
from app.db.models import User
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.documents import DocumentRepository
from app.domain.enums import SearchMode
from app.services.document_service import DOCUMENT_NOT_FOUND
from app.services.retrieval import (
    RankedChunk,
    from_keyword,
    from_semantic,
    reciprocal_rank_fusion,
    rerank,
)

logger = logging.getLogger(__name__)

SEARCH_UNAVAILABLE_MESSAGE = "Semantic search is temporarily unavailable; try mode=keyword"


@dataclass(frozen=True)
class SearchResult:
    mode: SearchMode
    results: list[RankedChunk]
    reranked: bool


class SearchService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        embedder: EmbeddingProvider | None,
        reranker: Reranker | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._embedder = embedder
        self._reranker = reranker
        self._chunks = ChunkRepository(session)
        self._documents = DocumentRepository(session)

    def validate_query(self, query: str) -> str:
        cleaned = query.strip()
        if not cleaned:
            raise InvalidQueryError("Query must not be empty")
        if len(cleaned) > self._settings.max_query_length:
            raise InvalidQueryError(
                f"Query must be at most {self._settings.max_query_length} characters"
            )
        return cleaned

    def resolve_top_k(self, top_k: int | None) -> int:
        value = self._settings.top_k if top_k is None else top_k
        if not 1 <= value <= self._settings.max_top_k:
            raise InvalidQueryError(f"top_k must be between 1 and {self._settings.max_top_k}")
        return value

    def _embed_query(self, query: str) -> list[float]:
        if self._embedder is None:
            raise ServiceUnavailableError(SEARCH_UNAVAILABLE_MESSAGE)
        try:
            return self._embedder.embed_query(query)
        except (EmbeddingError, AIProviderConfigurationError, OSError) as exc:
            logger.warning("search.embedding_failed", extra={"error_type": type(exc).__name__})
            raise ServiceUnavailableError(SEARCH_UNAVAILABLE_MESSAGE) from exc

    def search(
        self,
        *,
        owner: User,
        query: str,
        top_k: int | None = None,
        mode: SearchMode = SearchMode.HYBRID,
        document_id: uuid.UUID | None = None,
    ) -> SearchResult:
        started = time.perf_counter()
        query = self.validate_query(query)
        limit = self.resolve_top_k(top_k)
        if document_id is not None and self._documents.get_for_owner(document_id, owner.id) is None:
            raise NotFoundError(DOCUMENT_NOT_FOUND)

        use_reranker = self._reranker is not None
        pool = max(limit, self._settings.rerank_top_k) if use_reranker else limit
        candidates = max(self._settings.candidate_k, pool)

        if mode is SearchMode.SEMANTIC:
            vector = self._embed_query(query)
            ranked = from_semantic(
                self._chunks.semantic_search(
                    owner_id=owner.id, query_embedding=vector, limit=pool, document_id=document_id
                )
            )
        elif mode is SearchMode.KEYWORD:
            ranked = from_keyword(
                self._chunks.keyword_search(
                    owner_id=owner.id, query_text=query, limit=pool, document_id=document_id
                )
            )
        else:
            vector = self._embed_query(query)
            semantic_hits = self._chunks.semantic_search(
                owner_id=owner.id, query_embedding=vector, limit=candidates, document_id=document_id
            )
            keyword_hits = self._chunks.keyword_search(
                owner_id=owner.id,
                query_text=query,
                limit=candidates,
                document_id=document_id,
                query_embedding=vector,
            )
            ranked = reciprocal_rank_fusion(semantic_hits, keyword_hits)

        reranked = False
        if self._reranker is not None and ranked:
            try:
                ranked = rerank(query, ranked[:pool], self._reranker)
                reranked = True
            except (EmbeddingError, OSError) as exc:
                # Reranking is an optimisation; fall back to the first-stage order.
                logger.warning("search.rerank_failed", extra={"error_type": type(exc).__name__})

        results = ranked[:limit]
        logger.info(
            "search.completed",
            extra={
                "mode": mode.value,
                "top_k": limit,
                "result_count": len(results),
                "query_length": len(query),
                "document_filter": document_id is not None,
                "reranked": reranked,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return SearchResult(mode=mode, results=results, reranked=reranked)
