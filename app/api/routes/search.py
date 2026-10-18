from fastapi import APIRouter, Depends

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.rate_limit import limit_by_user
from app.api.dependencies.services import AnswerServiceDep, SearchServiceDep
from app.api.responses import error_responses
from app.schemas.search import (
    AskRequest,
    AskResponse,
    ChunkResult,
    Citation,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(tags=["search"])

SNIPPET_CHARS = 300


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Search my documents",
    description=(
        "Retrieve passages from your own **completed** documents. `mode`: `semantic` "
        "(pgvector cosine), `keyword` (PostgreSQL full-text, ts_rank) or `hybrid` "
        "(Reciprocal Rank Fusion of both, default). Does not call a language model."
    ),
    responses=error_responses(401, 404, 422, 429, 503),
    dependencies=[Depends(limit_by_user("search"))],
)
def search(body: SearchRequest, user: CurrentUser, service: SearchServiceDep) -> SearchResponse:
    result = service.search(
        owner=user,
        query=body.query,
        top_k=body.top_k,
        mode=body.mode,
        document_id=body.document_id,
    )
    return SearchResponse(
        query=body.query.strip(),
        mode=result.mode,
        reranked=result.reranked,
        results=[
            ChunkResult(
                chunk_id=item.hit.chunk_id,
                document_id=item.hit.document_id,
                filename=item.hit.filename,
                chunk_index=item.hit.chunk_index,
                text=item.hit.content,
                page_start=item.hit.page_start,
                page_end=item.hit.page_end,
                char_start=item.hit.char_start,
                char_end=item.hit.char_end,
                token_count=item.hit.token_count,
                score=item.score,
                similarity=item.hit.similarity,
                semantic_rank=item.semantic_rank,
                keyword_rank=item.keyword_rank,
            )
            for item in result.results
        ],
    )


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a question about my documents",
    description=(
        "Hybrid retrieval over your completed documents, then a grounded answer from the "
        "configured LLM with citations restricted to the retrieved passages. If no passage "
        "reaches the evidence threshold, an insufficient-evidence answer is returned "
        "without calling the LLM. 503 if the LLM is unavailable or not configured."
    ),
    responses=error_responses(401, 404, 422, 429, 503),
    dependencies=[Depends(limit_by_user("ask"))],
)
def ask(body: AskRequest, user: CurrentUser, service: AnswerServiceDep) -> AskResponse:
    result = service.ask(
        owner=user, question=body.question, top_k=body.top_k, document_id=body.document_id
    )
    return AskResponse(
        answer=result.answer,
        insufficient_evidence=result.insufficient_evidence,
        citations=[
            Citation(
                source_id=cited.label,
                chunk_id=cited.source.item.hit.chunk_id,
                document_id=cited.source.item.hit.document_id,
                filename=cited.source.item.hit.filename,
                chunk_index=cited.source.item.hit.chunk_index,
                page_start=cited.source.item.hit.page_start,
                page_end=cited.source.item.hit.page_end,
                char_start=cited.source.item.hit.char_start,
                char_end=cited.source.item.hit.char_end,
                snippet=cited.source.item.hit.content[:SNIPPET_CHARS],
            )
            for cited in result.citations
        ],
        sources_considered=result.sources_considered,
        model=result.model,
        warnings=result.warnings,
    )
