import uuid

from app.db.repositories.chunks import ChunkHit
from app.services.retrieval import RRF_K, reciprocal_rank_fusion, rerank
from tests.fakes import ReverseReranker


def _hit(n: int, *, similarity: float | None = None, keyword: float | None = None) -> ChunkHit:
    return ChunkHit(
        chunk_id=uuid.UUID(int=n),
        document_id=uuid.UUID(int=1000),
        filename="doc.txt",
        chunk_index=n,
        content="x" * n,
        page_start=None,
        page_end=None,
        char_start=0,
        char_end=n,
        token_count=n,
        similarity=similarity,
        keyword_score=keyword,
    )


def test_rrf_scores_and_merges_duplicates() -> None:
    semantic = [_hit(1, similarity=0.9), _hit(2, similarity=0.8)]
    keyword = [_hit(2, keyword=0.5), _hit(3, keyword=0.4)]
    fused = reciprocal_rank_fusion(semantic, keyword)
    assert [item.hit.chunk_index for item in fused] == [2, 1, 3]
    top = fused[0]
    assert top.score == 1 / (RRF_K + 2) + 1 / (RRF_K + 1)
    assert (top.semantic_rank, top.keyword_rank) == (2, 1)
    # Merged hit keeps the similarity and gains the keyword score.
    assert top.hit.similarity == 0.8
    assert top.hit.keyword_score == 0.5
    assert len({item.hit.chunk_id for item in fused}) == len(fused)


def test_rrf_ties_are_deterministic() -> None:
    fused = reciprocal_rank_fusion([_hit(7)], [_hit(3)])
    assert fused[0].score == fused[1].score
    assert [item.hit.chunk_index for item in fused] == [3, 7]  # ordered by chunk id


def test_rrf_ignores_repeated_ids_within_a_list() -> None:
    fused = reciprocal_rank_fusion([_hit(1), _hit(1)], [])
    assert len(fused) == 1
    assert fused[0].score == 1 / (RRF_K + 1)


def test_rrf_empty_inputs() -> None:
    assert reciprocal_rank_fusion([], []) == []


def test_rerank_reorders_by_score() -> None:
    fused = reciprocal_rank_fusion([_hit(1), _hit(5)], [_hit(3)])
    reranker = ReverseReranker()
    reranked = rerank("query", fused, reranker)
    assert [item.hit.chunk_index for item in reranked] == [5, 3, 1]
    assert reranked[0].rerank_score == 5.0
    assert reranker.calls == 1
