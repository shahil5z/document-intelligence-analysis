"""Retrieval evaluation on the synthetic set in tests/fixtures (Recall@k, Precision@k, MRR).

Usage:
    uv run python scripts/evaluate_retrieval.py \
        --database-url postgresql+psycopg://user:pw@localhost:5432/dip_eval_test \
        [--provider sentence-transformers|hashing] [--k 1 3 5] [--json results.json]

Runs the production code path: TXT extraction, normalization, chunking, embedding,
``document_chunks`` inserts and ``SearchService`` queries against PostgreSQL + pgvector.
It creates a throwaway user with completed documents and deletes it at the end. The
database name must contain "test" or "eval" (the schema is migrated to head).

Relevance: a retrieved chunk is relevant when it comes from the query's document and
contains the query's phrase (case-insensitive). Each query has one target passage, so
Recall@k is the share of queries with a relevant chunk in the top k (hit rate),
Precision@k = relevant chunks in top k / k, MRR uses the first relevant rank (0 if none
within max k).
"""

import argparse
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


def _configure_environment(database_url: str) -> None:
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    name = make_url(database_url).database or ""
    if "test" not in name and "eval" not in name:
        raise SystemExit("Refusing to run: database name must contain 'test' or 'eval'")
    os.environ["DATABASE_URL"] = database_url
    os.environ["APP_ENV"] = "test"
    os.environ.setdefault("JWT_SECRET_KEY", secrets.token_urlsafe(48))
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:  # noqa: PLR0915
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--provider", choices=["sentence-transformers", "hashing"], default="sentence-transformers"
    )
    parser.add_argument("--k", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--chunk-size", type=int, default=120)
    parser.add_argument("--chunk-overlap", type=int, default=20)
    parser.add_argument("--json", type=Path, help="Write the metrics to this file.")
    args = parser.parse_args()
    _configure_environment(args.database_url)

    from alembic.config import Config  # noqa: PLC0415

    from alembic import command  # noqa: PLC0415
    from app.ai.embeddings import embed_in_batches  # noqa: PLC0415
    from app.ai.factory import create_embedding_provider  # noqa: PLC0415
    from app.core.config import get_settings  # noqa: PLC0415
    from app.db.models import Document, User  # noqa: PLC0415
    from app.db.repositories.chunks import ChunkRepository, NewChunk  # noqa: PLC0415
    from app.db.session import get_session_factory  # noqa: PLC0415
    from app.domain.enums import DocumentStatus, SearchMode  # noqa: PLC0415
    from app.processing.chunking import (  # noqa: PLC0415
        ApproximateTokenCounter,
        RecursiveTokenChunker,
        TokenCounter,
    )
    from app.processing.extraction import TextExtractor  # noqa: PLC0415
    from app.processing.normalization import normalize_content  # noqa: PLC0415
    from app.services.search_service import SearchService  # noqa: PLC0415

    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    command.upgrade(alembic_config, "head")

    settings = get_settings().model_copy(
        update={"chunk_size": args.chunk_size, "chunk_overlap": args.chunk_overlap}
    )
    counter: TokenCounter
    if args.provider == "hashing":
        from tests.fakes import HashingEmbeddingProvider  # noqa: PLC0415

        embedder: Any = HashingEmbeddingProvider()
        counter = ApproximateTokenCounter()
    else:
        embedder = create_embedding_provider(settings)
        counter = embedder
    chunker = RecursiveTokenChunker(
        counter,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        max_chunks=settings.max_chunks_per_document,
    )
    spec = json.loads((FIXTURES / "eval_queries.json").read_text(encoding="utf-8"))
    max_k = max(args.k)
    factory = get_session_factory()
    session = factory()
    user = User(email=f"eval-{uuid.uuid4().hex[:10]}@example.com", password_hash="!")  # noqa: S106
    session.add(user)
    session.flush()
    total_chunks = 0
    try:
        for path in sorted((FIXTURES / "documents").glob("*.txt")):
            data = path.read_bytes()
            document = Document(
                owner_id=user.id,
                filename=f"{uuid.uuid4().hex}.txt",
                original_filename=path.name,
                content_type="text/plain",
                file_size=len(data),
                storage_key=f"eval/{uuid.uuid4().hex}.txt",
                checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                status=DocumentStatus.COMPLETED,
            )
            session.add(document)
            session.flush()
            chunks = chunker.chunk(normalize_content(TextExtractor().extract(data)))
            vectors = embed_in_batches(
                embedder, [c.text for c in chunks], settings.embedding_batch_size
            )
            ChunkRepository(session).replace_for_document(
                document_id=document.id,
                owner_id=user.id,
                chunks=[
                    NewChunk(
                        chunk_index=c.index,
                        content=c.text,
                        page_start=c.page_start,
                        page_end=c.page_end,
                        char_start=c.char_start,
                        char_end=c.char_end,
                        token_count=c.token_count,
                        embedding=v,
                    )
                    for c, v in zip(chunks, vectors, strict=True)
                ],
                embedding_model=embedder.model_name,
            )
            total_chunks += len(chunks)
        session.commit()

        service = SearchService(session, settings, embedder)
        report: dict[str, Any] = {
            "provider": args.provider,
            "model": embedder.model_name,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "documents": len(list((FIXTURES / "documents").glob("*.txt"))),
            "chunks": total_chunks,
            "queries": len(spec["queries"]),
            "modes": {},
        }
        for mode in SearchMode:
            recall = dict.fromkeys(args.k, 0.0)
            precision = dict.fromkeys(args.k, 0.0)
            reciprocal_ranks = 0.0
            misses: list[str] = []
            for item in spec["queries"]:
                results = service.search(
                    owner=user, query=item["query"], top_k=max_k, mode=mode
                ).results
                relevant = [
                    r.hit.filename == item["document"]
                    and item["phrase"].lower() in r.hit.content.lower()
                    for r in results
                ]
                first = next((i for i, rel in enumerate(relevant, start=1) if rel), None)
                reciprocal_ranks += 1.0 / first if first else 0.0
                if first is None:
                    misses.append(item["query"])
                for k in args.k:
                    recall[k] += 1.0 if any(relevant[:k]) else 0.0
                    precision[k] += sum(relevant[:k]) / k
            n = len(spec["queries"])
            report["modes"][mode.value] = {
                **{f"recall@{k}": round(recall[k] / n, 3) for k in args.k},
                **{f"precision@{k}": round(precision[k] / n, 3) for k in args.k},
                f"mrr@{max_k}": round(reciprocal_ranks / n, 3),
                "misses": misses,
            }
    finally:
        session.rollback()
        session.delete(session.merge(user))
        session.commit()
        session.close()

    print(
        f"provider={report['provider']} model={report['model']} documents={report['documents']} "
        f"chunks={report['chunks']} queries={report['queries']} "
        f"chunk_size={report['chunk_size']} overlap={report['chunk_overlap']}"
    )
    header = [*[f"R@{k}" for k in args.k], *[f"P@{k}" for k in args.k], f"MRR@{max_k}"]
    print("| mode | " + " | ".join(header) + " |")
    print("| --- |" + " --- |" * len(header))
    for mode, metrics in report["modes"].items():
        values = [
            *[metrics[f"recall@{k}"] for k in args.k],
            *[metrics[f"precision@{k}"] for k in args.k],
            metrics[f"mrr@{max_k}"],
        ]
        print(f"| {mode} | " + " | ".join(f"{v:.3f}" for v in values) + " |")
        if metrics["misses"]:
            print(f"  misses ({mode}): {metrics['misses']}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
