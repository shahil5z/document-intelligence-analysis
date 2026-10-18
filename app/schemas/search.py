import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import SearchMode

# Hard upper bounds for request validation; the configured MAX_TOP_K / MAX_QUERY_LENGTH
# (which may be lower) are enforced by the service with the same 422 envelope.
TOP_K_HARD_LIMIT = 100
QUERY_HARD_LIMIT = 10_000


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=QUERY_HARD_LIMIT, examples=["refund window"])
    top_k: int | None = Field(
        default=None, ge=1, le=TOP_K_HARD_LIMIT, description="Defaults to TOP_K; max MAX_TOP_K."
    )
    mode: SearchMode = SearchMode.HYBRID
    document_id: uuid.UUID | None = Field(
        default=None, description="Restrict the search to one of your documents."
    )


class ChunkResult(BaseModel):
    """A retrieved passage. Embedding vectors are never returned."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    text: str
    page_start: int | None
    page_end: int | None
    char_start: int = Field(description="Offset into the normalized extracted text.")
    char_end: int
    token_count: int
    score: float = Field(
        description="Mode-specific: cosine similarity (semantic), ts_rank (keyword), "
        "RRF score (hybrid) or cross-encoder score (reranked)."
    )
    similarity: float | None = Field(default=None, description="Cosine similarity, if computed.")
    semantic_rank: int | None = None
    keyword_rank: int | None = None


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    reranked: bool
    results: list[ChunkResult]


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        min_length=1, max_length=QUERY_HARD_LIMIT, examples=["How long is the refund window?"]
    )
    top_k: int | None = Field(default=None, ge=1, le=TOP_K_HARD_LIMIT)
    document_id: uuid.UUID | None = None


class Citation(BaseModel):
    source_id: str = Field(examples=["S1"], description="Label used in the answer text.")
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    snippet: str = Field(description="First characters of the cited passage.")


class AskResponse(BaseModel):
    answer: str
    insufficient_evidence: bool
    citations: list[Citation]
    sources_considered: int = Field(description="Passages sent to the language model.")
    model: str | None = Field(description="LLM used; null when no LLM call was made.")
    warnings: list[str] = Field(default_factory=list)
