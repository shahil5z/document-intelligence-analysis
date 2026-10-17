# DIP2 handoff: extraction, chunking, embeddings, search, `/ask`

DIP1 delivered the foundation only. Nothing in this file is implemented yet unless it
names an existing path.

## What exists (read these first)

| Concern | File |
| --- | --- |
| App factory, middleware, routers | `app/main.py`, `app/api/router.py` |
| Settings (add new env vars here) | `app/core/config.py` |
| Models | `app/db/models/{user,document,processing_job,audit_log}.py` |
| Owner-scoped queries | `app/db/repositories/documents.py` |
| Upload use case | `app/services/document_service.py` |
| Status enums / transitions | `app/domain/enums.py`, `app/domain/state_machine.py` |
| Celery app / task | `app/workers/celery_app.py`, `app/workers/tasks.py` (`documents.process`) |
| Job execution (framework-free) | `app/workers/processing.py` (`DocumentProcessor`) |
| Pipeline extension point | `app/workers/pipeline.py` (`PipelineStep`, `build_default_pipeline`) |
| Storage interface | `app/storage/base.py` (`save`, `iter_chunks`, `delete`, `exists`) |
| Initial migration | `alembic/versions/20261017_0001_initial_schema.py` (enables `vector`) |
| Test fixtures | `tests/conftest.py` (real PostgreSQL, `RecordingDispatcher`, per-test truncation) |

## Lifecycles

- Document: `uploaded -> queued -> processing -> completed | failed`; transient retry
  `processing -> queued`; `completed|failed -> queued` reserved for reprocessing.
- Job: `pending -> queued -> processing -> completed | failed | retrying`;
  `retrying -> processing | failed`. Terminal jobs are never reused; reprocessing should
  create a new job row and publish a new task.
- Always change status through `transition_document` / `transition_job`.

## Where the new work goes

1. **Extraction** - new `PipelineStep` classes, e.g. `app/workers/steps/extract.py`
   (`PdfTextExtractor`, `DocxTextExtractor`, `PlainTextExtractor`, OCR fallback). Read bytes
   with `context.storage.iter_chunks(context.storage_key)`; dispatch on
   `context.content_type`. Raise `PermanentProcessingError("safe message")` for corrupt
   files and `TransientProcessingError` for retryable dependency failures.
2. **Chunking** - another step producing chunk records (text, ordinal, page/section,
   char offsets for citations).
3. **Embeddings** - a step calling an embedding provider behind a small protocol
   (`app/services/embeddings.py` or `app/workers/steps/embed.py`) so tests can fake it.
4. **Register steps** in `build_default_pipeline()` in order:
   `IntegrityCheckStep -> extract -> chunk -> embed`. Steps currently share only
   `PipelineContext`; if steps need to pass data (text, chunks), extend the context with
   a mutable artefacts field or let steps persist to the database via a session factory
   passed in by `DocumentProcessor`.
5. **Vector index / tables** - new models in `app/db/models/` (e.g. `document_chunks`
   with `document_id` FK `ON DELETE CASCADE`, `owner_id` denormalised for filtered
   search, `embedding vector(N)`), exported from `app/db/models/__init__.py`.
6. **Search** - `app/services/search_service.py` + `app/api/routes/search.py`. Every query
   must filter by `owner_id` (copy the pattern in `DocumentRepository`). Hybrid retrieval:
   PostgreSQL full-text (`tsvector`) + vector similarity, merged in the service.
7. **`/ask`** - `app/api/routes/ask.py` + `app/services/answer_service.py`; retrieve chunks
   via the search service, call the LLM behind a protocol, return answer + citations
   (document id, chunk id, page/offsets). Register routers in `app/api/router.py`.
8. **Status semantics** - once extraction exists, `completed` should mean "indexed";
   update the docstring in `DocumentStatus` and the README.

## Extending the schema

```bash
uv run alembic revision -m "add document chunks"      # edit by hand
uv run alembic upgrade head && uv run alembic check   # check must report no diff
```

- `pgvector` Python package provides `Vector` for SQLAlchemy; add it with `uv add pgvector`.
- Add HNSW/IVFFlat indexes in the migration (`op.execute(...)` or `op.create_index(...,
  postgresql_using="hnsw", postgresql_ops={...})`).
- New ENUM values need `ALTER TYPE ... ADD VALUE` in a migration.
- Never modify revision `0001`.

## Do not rewrite

- Ownership enforcement in repositories (404 for foreign resources).
- Upload validation and storage ordering in `DocumentService.upload` (file -> commit ->
  publish; job is `queued` before commit).
- Session handling (`app/api/dependencies/db.py`, `app/db/session.py::session_scope`).
- The error envelope, request-id middleware and logging format.
- `DocumentProcessor` claim/finish logic (row lock, idempotency, safe error messages);
  extend through pipeline steps instead.

## Testing guidance

Add tests next to the existing ones: unit tests for steps with in-memory bytes,
integration tests with `DocumentProcessor` + `LocalStorage` + test DB (see
`tests/integration/test_processing.py`), and API tests via the `client` fixture.
Fake embedding/LLM providers; do not call external APIs in the suite.
