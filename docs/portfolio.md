# Portfolio notes: Document Intelligence Platform (DIP1)

A concise, interview-oriented view. Every claim below was executed during DIP1; items
that are planned are labelled as such.

## One-line summary

A FastAPI + PostgreSQL + Celery backend that accepts user documents, stores them
safely, and processes them asynchronously with explicit job states - the foundation for
retrieval and cited question answering (planned, DIP2).

## Problems solved and how

| Problem | Approach | Evidence |
| --- | --- | --- |
| One user must never see another's documents | Owner filter inside every repository query; foreign ids return 404 | API tests + smoke test (second user gets 404 on get/status/delete, empty list) |
| Uploads must not trust the client | Extension + content-type allow-list, magic bytes, streamed size limit, sanitised names, server-side storage keys, traversal guard | 16 validation tests, 10 storage tests, 413/415/400 API tests |
| Background jobs must be observable and safe to retry | DB-backed job state machine, task id stored before publish, row lock, idempotent re-delivery, safe error messages | 6 integration tests with the real database; real worker in compose |
| Secrets must not leak | `SecretStr`, value-free config errors, placeholder rejection, log redaction, Redis AUTH, generated `.env` | config/generate_env tests; secret values found 0 times in container logs |
| Operability | JSON logs with request ids propagated to the worker, uniform error envelope, liveness/readiness | tests + compose run |

## Engineering practices shown

- Layered design (routes -> services -> repositories), explicit transactions, ADRs for
  the main choices including a deliberate sync-vs-async decision.
- Tests against a real PostgreSQL database using the real Alembic migrations (128 tests,
  94 % line coverage of `app/` in the last run); ruff and strict mypy clean.
- Hand-written migration verified with `alembic check`.
- Reproducible container build (`--no-cache`), non-root image, healthchecks, migrate
  service, end-to-end smoke script.
- Small commits that each import cleanly.

## Talking points / trade-offs

- **Sync SQLAlchemy**: one code path for API and Celery; throughput not measured yet,
  so async was not justified (ADR-005).
- **Job state in PostgreSQL, not Celery results**: the API can always answer "what
  happened to my document", and publishing does not depend on the result backend.
- **File first, then commit, then publish**: avoids workers seeing uncommitted jobs and
  leaves at worst an orphan file, never a dangling record.
- **404 instead of 403** for other users' resources to prevent id enumeration.

## Not done yet (be explicit in interviews)

Extraction, OCR, chunking, embeddings, vector/hybrid search and `/ask` with citations
(DIP2); CI/CD, rate limiting, metrics/tracing, image scanning (DIP3). No load or
performance measurements exist.
