# DIP3 handoff: tests, CI/CD, observability, rate limiting, hardening

## Verified state at the end of DIP2

Details: [DIP2_HANDOFF.md](DIP2_HANDOFF.md#tests-executed-and-real-results). Last run:
247 tests passed, 2 skipped (Redis readiness, no `TEST_REDIS_URL`), 94 % line coverage;
ruff and mypy strict clean; `alembic check` clean with revisions `0001` + `0002`; compose
stack on fresh volumes passed the extended smoke test (search modes, cross-user
isolation, `/ask` with a stub LLM, reprocess, delete). Real OpenAI `/ask` and the real
reranker are NOT VERIFIED.

### DIP2 files (added / modified)

- Added: `app/processing/` (content, extraction, normalization, chunking),
  `app/ai/embeddings.py`, `reranker.py`, `llm.py`, `app/db/models/document_chunk.py`,
  `app/db/repositories/chunks.py`, `app/services/retrieval.py`, `search_service.py`,
  `answer_service.py`, `rag_prompt.py`, `app/schemas/search.py`,
  `app/api/routes/search.py`, `app/workers/steps.py`,
  `alembic/versions/20261018_0002_document_chunks.py`, `scripts/evaluate_retrieval.py`,
  `scripts/calibrate_evidence_threshold.py`, test files listed in DIP2_HANDOFF, docs.
- Modified: `app/ai/base.py`, `errors.py`, `factory.py`, `openai_provider.py`,
  `app/core/config.py`, `errors.py`, `app/domain/enums.py`, `app/db/models/processing_job.py`,
  `app/api/dependencies/services.py`, `app/api/routes/documents.py`, `app/api/router.py`,
  `app/main.py`, `app/schemas/document.py`, `app/services/document_service.py`,
  `app/workers/pipeline.py`, `processing.py`, `tasks.py`, `pyproject.toml`, `uv.lock`,
  `Dockerfile`, `docker-compose.yml`, `.env.example`, `scripts/smoke_test.py`,
  `tests/conftest.py`, `tests/unit/test_config.py`.

### What not to rewrite

The retrieval SQL filters (`ChunkRepository._base`), the embed-then-lock-and-replace
order in `IndexStep`, citation validation and prompt escaping, lazy model imports, and the
job state machine. Extend them; see DIP2_HANDOFF "What DIP3 must not break".

## Verified state at the end of DIP1

Full results, the test inventory and failures seen during development are in
[DIP1_HANDOFF.md section 12-13](DIP1_HANDOFF.md#12-tests-executed-and-real-results).
Summary of the last run: 128 tests passed (94 % line coverage of `app/`), ruff check and
format clean, mypy strict clean, `alembic check` clean, compose stack healthy from a
`--no-cache` build on fresh volumes, smoke test passed, Redis rejects unauthenticated
commands. Without `TEST_REDIS_URL`, two readiness tests are skipped.

### Missing tests (DIP2 additions)

- Real OpenAI `/ask` run (key only on the Windows host; not verified).
- Real cross-encoder reranker (only a fake in tests).
- Prompt-injection evaluation against a real model; answer faithfulness metrics.
- Larger retrieval evaluation set (current: 18 queries, 6 documents); HNSW recall vs
  exact search; latency / throughput of embedding and search.
- Concurrent reprocess + delete races beyond the single-process integration tests.
- Malformed-PDF fuzzing (only one corrupt, one encrypted, one scanned fixture).

### Missing tests (from DIP1)

- Celery task adapter (`app/workers/tasks.py`, 56 % covered) and `CeleryDocumentTaskDispatcher`
  against a real broker (exercised only by the manual compose smoke test).
- `app/cli.py` (0 % covered; exercised manually in compose).
- Concurrency: two deliveries of one task at once (row lock), duplicate upload race (unique
  constraint path).
- Storage delete failure after DB delete; DB commit failure after file save.
- Token for a deleted user; tokens with tampered `role` claim.
- DIP1 OpenAI SDK adapters against the real API (only a fake client is used; still unused by `/ask`).
- Windows host run (README notes are untested).
- Load / performance tests: not measured yet.

## CI/CD (to build)

Suggested GitHub Actions jobs:
1. `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy`.
2. Tests with a `pgvector/pgvector:pg16` service container and `redis:7-alpine` started
   with `--requirepass`; set `TEST_DATABASE_URL` and `TEST_REDIS_URL=redis://:<pw>@localhost:6379/0`
   from CI secrets or per-run random values. No `OPENAI_API_KEY` and no model download
   are needed (tests use a hashing embedder and a mock LLM).
3. `alembic upgrade head && alembic check` against an empty database.
4. `docker build`, image scan (e.g. Trivy), optional compose smoke test: create `.env`
   with `python scripts/generate_env.py`, `docker compose up -d`, `scripts/smoke_test.py`.
   Cache the Hugging Face model (`model_cache` volume / CI cache) or the first document
   waits for the download; use `--ask-expect unavailable` without an LLM key.
5. Secret scanning of tracked files (e.g. gitleaks); `.env` and `/env` are git-ignored.

## Rate limiting

Not implemented. Hook: `app/main.py::_register_middleware` (add inside
`RequestContextMiddleware` so 429 responses carry a request id; use the `rate_limited`
error code already mapped in `app/core/errors.py`). Priorities: `/auth/login`,
`/auth/token`, `/auth/register` (per IP + per email), `POST /documents` (per user),
`POST /ask` (per user; each call can cost LLM tokens), `POST /search` and
`POST /documents/{id}/reprocess` (CPU-bound embedding).
Redis is already available for counters.

## Observability

- Logs: JSON to stdout (`app/core/logging.py`), request ids propagate to worker logs.
- DIP2 log events: `search.completed`, `ask.completed`, `ask.insufficient_evidence`,
  `llm.completed`, `llm.timeout` / `llm.http_error` / `llm.transport_error` / `llm.malformed_response`, `ask.llm_failed`, `search.embedding_failed`, `search.rerank_failed`, `embedding.model_loaded`, job `stage` updates. Token
  usage fields in `llm.completed` are redacted by the key-name redactor (rename them).
- Missing: metrics (request latency/status, job durations per stage, queue depth,
  LLM latency/tokens, insufficient-evidence rate), tracing
  (OpenTelemetry for FastAPI, SQLAlchemy, Celery), log shipping, alerting.
- `RequestContextMiddleware` (`app/core/middleware.py`) already measures `duration_ms`
  per request; a metrics exporter can hook there.

## Security hardening areas

- Request body limit before multipart parsing (proxy `client_max_body_size` or ASGI middleware).
- Account lockout / login throttling; refresh tokens and revocation (`jti` is already issued).
- Deeper DOCX validation, malware scanning, PDF sanitising; run parsers in a sandboxed
  process with memory/CPU limits (pypdf runs inside the worker today).
- Model supply chain: pin model revisions (commit hashes) and verify them; today the
  model is fetched by name.
- Password policy beyond length (12-128 chars today), breached-password check.
- Security headers (HSTS, CSP for docs pages) at the proxy or middleware.
- Audit log retention and immutability (DB permissions); PII review of audit metadata
  (original filenames are stored).
- Secrets via a secret manager; JWT key rotation (consider asymmetric keys).
- Redis password is passed on the `redis-server` command line (visible via `docker inspect`);
  prefer a mounted config file or ACL file.
- Redis has no TLS; Postgres connections are not TLS either (fine on the compose network only).

## Container security

- Current: two-stage Dockerfile, `python:3.12-slim`, uv-installed locked dependencies,
  non-root user uid 10001, healthcheck, Postgres/Redis not published to the host.
- DIP2 adds ~1.3 GB (CPU torch); consider a separate embedding service or ONNX export.
- Missing: pinned base image digests, image scanning, read-only root filesystem,
  dropped capabilities / `no-new-privileges` in compose, resource limits, SBOM.

## Docker notes from DIP1 / DIP2

DIP2: on the same box, containers on compose networks could not resolve external hosts
(`huggingface.co`); the run used a pre-seeded `model_cache` volume with `HF_HUB_OFFLINE=1`.
Building with `docker compose build` tags `document-intelligence-platform:local`, which
any other checkout of this project on the same host also uses.


The dev box had stale `iptables-legacy` rules (FORWARD policy DROP) that blocked traffic
between containers on compose networks; it was worked around on that box with
`iptables-legacy -I DOCKER-USER -i br-+ -o br-+ -j ACCEPT`. This is a host quirk, not a
project requirement.
