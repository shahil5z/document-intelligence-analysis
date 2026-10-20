"""DIP2 pipeline steps: extract -> normalize -> chunk -> embed -> index -> suggest.

Each step reads and writes ``context.state``. Expected, non-retryable problems raise
``PermanentProcessingError`` with a user-safe message (no parser or model details).
Embedding happens outside any database transaction; ``IndexStep`` replaces the
document's chunks in one short transaction (delete + insert), which makes re-delivery
and reprocessing idempotent.
"""

import logging
import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.ai.base import EmbeddingProvider, LLMProvider
from app.ai.embeddings import embed_in_batches
from app.ai.errors import AIProviderConfigurationError
from app.ai.suggestions import generate_suggested_questions
from app.core.config import Settings
from app.db.models import Document
from app.db.repositories.chunks import ChunkRepository, NewChunk
from app.db.session import session_scope
from app.processing.chunking import (
    ChunkLimitExceededError,
    RecursiveTokenChunker,
    TokenCounter,
)
from app.processing.extraction import ExtractionError, ExtractorRegistry, default_registry
from app.processing.normalization import normalize_content
from app.workers.pipeline import (
    DocumentPipeline,
    IntegrityCheckStep,
    PermanentProcessingError,
    PipelineContext,
)

logger = logging.getLogger(__name__)

NO_TEXT_MESSAGE = (
    "No extractable text was found. Scanned documents and images are not supported "
    "(OCR is not implemented)."
)


class ExtractStep:
    name = "extract"

    def __init__(self, registry: ExtractorRegistry) -> None:
        self._registry = registry

    def run(self, context: PipelineContext) -> None:
        started = time.perf_counter()
        data = b"".join(context.storage.iter_chunks(context.storage_key))
        try:
            content = self._registry.for_content_type(context.content_type).extract(data)
        except ExtractionError as exc:
            raise PermanentProcessingError(exc.safe_message) from exc
        context.state.content = content
        logger.info(
            "pipeline.extracted",
            extra={
                "format": content.source_format,
                "page_count": content.page_count,
                "char_count": content.char_count,
                "warnings": list(content.warnings),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )


class NormalizeStep:
    name = "normalize"

    def run(self, context: PipelineContext) -> None:
        if context.state.content is None:
            raise PermanentProcessingError(NO_TEXT_MESSAGE)
        content = normalize_content(context.state.content)
        if not content.has_text:
            raise PermanentProcessingError(NO_TEXT_MESSAGE)
        context.state.content = content


class ChunkStep:
    name = "chunk"

    def __init__(self, chunker: RecursiveTokenChunker, max_chunks: int) -> None:
        self._chunker = chunker
        self._max_chunks = max_chunks

    def run(self, context: PipelineContext) -> None:
        if context.state.content is None:
            raise PermanentProcessingError(NO_TEXT_MESSAGE)
        try:
            chunks = self._chunker.chunk(context.state.content)
        except ChunkLimitExceededError as exc:
            raise PermanentProcessingError(
                f"The document is too large to index (more than {exc.limit} chunks)"
            ) from exc
        if not chunks:
            raise PermanentProcessingError(NO_TEXT_MESSAGE)
        context.state.chunks = chunks
        logger.info(
            "pipeline.chunked",
            extra={
                "chunk_count": len(chunks),
                "max_chunk_tokens": max(chunk.token_count for chunk in chunks),
            },
        )


class EmbedStep:
    name = "embed"

    def __init__(self, embedder: EmbeddingProvider, batch_size: int) -> None:
        self._embedder = embedder
        self._batch_size = batch_size

    def run(self, context: PipelineContext) -> None:
        started = time.perf_counter()
        try:
            vectors = embed_in_batches(
                self._embedder, [chunk.text for chunk in context.state.chunks], self._batch_size
            )
        except AIProviderConfigurationError as exc:
            # Misconfiguration (e.g. dimension mismatch) will not fix itself on retry.
            logger.error("pipeline.embedding_misconfigured")
            raise PermanentProcessingError(
                "Embedding is misconfigured on the server; contact the administrator"
            ) from exc
        context.state.embeddings = vectors
        logger.info(
            "pipeline.embedded",
            extra={
                "count": len(vectors),
                "model": self._embedder.model_name,
                "batch_size": self._batch_size,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )


class IndexStep:
    name = "index"

    def __init__(self, session_factory: sessionmaker[Session], embedding_model: str) -> None:
        self._session_factory = session_factory
        self._embedding_model = embedding_model

    def run(self, context: PipelineContext) -> None:
        chunks, vectors = context.state.chunks, context.state.embeddings
        if len(chunks) != len(vectors):
            raise PermanentProcessingError("Indexing failed due to an internal error")
        with session_scope(self._session_factory) as session:
            # Lock the document row: a concurrent delete waits (or has already removed the
            # row, in which case there is nothing to index).
            exists = session.scalar(
                select(Document.id).where(Document.id == context.document_id).with_for_update()
            )
            if exists is None:
                logger.info("pipeline.index_skipped_document_deleted")
                return
            ChunkRepository(session).replace_for_document(
                document_id=context.document_id,
                owner_id=context.owner_id,
                chunks=[
                    NewChunk(
                        chunk_index=chunk.index,
                        content=chunk.text,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        token_count=chunk.token_count,
                        embedding=vector,
                    )
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ],
                embedding_model=self._embedding_model,
            )
            session.commit()
        logger.info("pipeline.indexed", extra={"chunk_count": len(chunks)})


class SuggestQuestionsStep:
    """Best effort: generate suggested questions after indexing.

    Never raises. Any failure (no LLM, timeout, bad reply, database hiccup) is logged and
    leaves ``documents.suggested_questions`` null; the job still completes.
    """

    name = "suggest"

    def __init__(
        self, session_factory: sessionmaker[Session], llm: LLMProvider | None, max_chars: int
    ) -> None:
        self._session_factory = session_factory
        self._llm = llm
        self._max_chars = max_chars

    def run(self, context: PipelineContext) -> None:
        if self._llm is None or context.state.content is None:
            return
        started = time.perf_counter()
        try:
            text, _ = context.state.content.joined()
            questions = generate_suggested_questions(self._llm, text, max_chars=self._max_chars)
            with session_scope(self._session_factory) as session:
                session.execute(
                    update(Document)
                    .where(Document.id == context.document_id)
                    .values(suggested_questions=questions)
                )
                session.commit()
        except Exception as exc:  # must never fail the job
            logger.warning("pipeline.suggestions_failed", extra={"error_type": type(exc).__name__})
            return
        logger.info(
            "pipeline.suggestions",
            extra={
                "question_count": len(questions or []),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )


def build_indexing_pipeline(
    *,
    settings: Settings,
    session_factory: sessionmaker[Session],
    embedder: EmbeddingProvider,
    token_counter: TokenCounter,
    suggestion_llm: LLMProvider | None = None,
) -> DocumentPipeline:
    chunker = RecursiveTokenChunker(
        token_counter,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        max_chunks=settings.max_chunks_per_document,
    )
    return DocumentPipeline(
        [
            IntegrityCheckStep(),
            ExtractStep(default_registry(settings.max_docx_uncompressed_bytes)),
            NormalizeStep(),
            ChunkStep(chunker, settings.max_chunks_per_document),
            EmbedStep(embedder, settings.embedding_batch_size),
            IndexStep(session_factory, embedder.model_name),
            SuggestQuestionsStep(
                session_factory, suggestion_llm, settings.question_suggestions_max_input_chars
            ),
        ]
    )
