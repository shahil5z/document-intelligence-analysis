"""Pure ranking helpers: Reciprocal Rank Fusion and reranking (no I/O)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.ai.base import Reranker
from app.db.repositories.chunks import ChunkHit

# k=60 is the constant from Cormack, Clarke & Buettcher (SIGIR 2009); it damps the
# influence of the very top ranks so one list cannot dominate the fused order.
RRF_K = 60


@dataclass(frozen=True)
class RankedChunk:
    hit: ChunkHit
    score: float
    semantic_rank: int | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None


def _tie_break(chunk_id: uuid.UUID) -> str:
    return str(chunk_id)


def from_semantic(hits: Sequence[ChunkHit]) -> list[RankedChunk]:
    return [
        RankedChunk(hit=hit, score=hit.similarity or 0.0, semantic_rank=rank)
        for rank, hit in enumerate(hits, start=1)
    ]


def from_keyword(hits: Sequence[ChunkHit]) -> list[RankedChunk]:
    return [
        RankedChunk(hit=hit, score=hit.keyword_score or 0.0, keyword_rank=rank)
        for rank, hit in enumerate(hits, start=1)
    ]


def reciprocal_rank_fusion(
    semantic: Sequence[ChunkHit], keyword: Sequence[ChunkHit], *, k: int = RRF_K
) -> list[RankedChunk]:
    """Fuse two ranked lists by summing 1 / (k + rank); duplicates are merged by chunk id.

    RRF uses only ranks, so cosine similarities and ts_rank values (different, unbounded
    scales) never need calibrating against each other. Ties sort by chunk id.
    """
    scores: dict[uuid.UUID, float] = {}
    hits: dict[uuid.UUID, ChunkHit] = {}
    semantic_ranks: dict[uuid.UUID, int] = {}
    keyword_ranks: dict[uuid.UUID, int] = {}
    for rank, hit in enumerate(semantic, start=1):
        if hit.chunk_id in semantic_ranks:
            continue
        semantic_ranks[hit.chunk_id] = rank
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
        hits[hit.chunk_id] = hit
    for rank, hit in enumerate(keyword, start=1):
        if hit.chunk_id in keyword_ranks:
            continue
        keyword_ranks[hit.chunk_id] = rank
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
        existing = hits.get(hit.chunk_id)
        if existing is None:
            hits[hit.chunk_id] = hit
        elif existing.keyword_score is None:
            hits[hit.chunk_id] = replace(existing, keyword_score=hit.keyword_score)
    ordered = sorted(scores, key=lambda cid: (-scores[cid], _tie_break(cid)))
    return [
        RankedChunk(
            hit=hits[cid],
            score=scores[cid],
            semantic_rank=semantic_ranks.get(cid),
            keyword_rank=keyword_ranks.get(cid),
        )
        for cid in ordered
    ]


def rerank(query: str, ranked: Sequence[RankedChunk], reranker: Reranker) -> list[RankedChunk]:
    scores = reranker.score(query, [item.hit.content for item in ranked])
    rescored = [
        replace(item, rerank_score=score, score=score)
        for item, score in zip(ranked, scores, strict=True)
    ]
    return sorted(rescored, key=lambda item: (-item.score, _tie_break(item.hit.chunk_id)))
