# Document Intelligence Platform

Backend for ingesting documents and turning them into searchable, citable knowledge.
The project is built in three stages:

| Stage | Scope | Status |
| --- | --- | --- |
| **DIP1** | Foundation: auth, uploads, storage, async job pipeline, audit log, ops basics, Docker | **Implemented** |
| **DIP2** | Text extraction, chunking, local embeddings (pgvector), semantic / keyword / hybrid search, `/ask` with validated citations | **Implemented** (OCR not implemented) - see [DIP2_HANDOFF.md](DIP2_HANDOFF.md) |
| **DIP3** | Production hardening: rate limiting, body limits, security headers, Prometheus metrics, worker reliability, compose hardening, CI workflow, docs | **Implemented locally**; Docker-dependent parts **not verified** (no Docker on the dev machine) - see [DIP3_HANDOFF.md](DIP3_HANDOFF.md) |

## Why

Question answering over private documents is only as trustworthy as the system
underneath it: who uploaded what, whether a file was processed, why a job failed, and
whether one user can ever see another user's data. DIP1 builds that layer first, with
tests against a real PostgreSQL database; DIP2 adds retrieval and generation on top
without reworking ownership, job tracking or storage: every search query is filtered by
owner and processing status inside SQL, and answers cite only passages that were
actually retrieved.

## Architecture overview

```mermaid
flowchart LR
    client[Client] --> api[FastAPI API]
    api --> pg[(PostgreSQL + pgvector ext.)]
    api --> redis[(Redis broker, password)]
    api --> storage[[File storage]]
    worker[Celery worker] --> redis
    worker -->|chunks + vectors| pg
    worker --> storage
    worker --> model[[local embedding model]]
    api --> model
    api -->|/ask only| llm[OpenAI-compatible LLM]
```

Routes -> services (transaction boundaries) -> repositories (owner-scoped queries) ->
SQLAlchemy models. Uploads create a processing job that a Celery worker executes
(integrity check -> extract -> normalize -> chunk -> embed -> index); job and document
status follow an explicit state machine. Diagrams (system, upload flow,
job flow, ER) are in [docs/architecture.md](docs/architecture.md), decisions in
[docs/adr/](docs/adr), the full stage hand-off in [DIP1_HANDOFF.md](DIP1_HANDOFF.md).

## Stack

Python 3.12 · FastAPI · Pydantic v2 / pydantic-settings · SQLAlchemy 2.x (sync, psycopg 3)
· Alembic · PostgreSQL 16 (`pgvector/pgvector:pg16`) · Redis 7 · Celery 5 · PyJWT ·
pwdlib (Argon2id) · pypdf · python-docx · sentence-transformers (`BAAI/bge-small-en-v1.5`,
CPU torch) · pgvector (HNSW) · PostgreSQL full-text search · httpx2 (OpenAI-compatible
chat API) · uv · pytest · ruff · mypy (strict) · Docker / Docker Compose.

## Current capabilities

| Area | Status |
| --- | --- |
| Register / login (JSON and OAuth2 form) / `GET /auth/me`, JWT access tokens | Implemented, tested |
| Roles `user` / `admin`, admin-only user and audit-log listing | Implemented, tested |
| Upload PDF/DOCX/TXT with allow-list, magic-byte check, streamed size limit, SHA-256, per-user duplicate detection (409) | Implemented, tested |
| List (paginated), detail, status, delete - strictly per owner (404 for others) | Implemented, tested |
| Celery job per upload: claim, integrity check (size + SHA-256), complete/fail, retries for transient errors, current `stage` on the job | Implemented, tested; run end to end with a real worker |
| Text extraction: PDF (pypdf, page numbers), DOCX (python-docx, paragraphs + tables), TXT (BOM / UTF-8 / cp1252); safe failures for empty, corrupt, encrypted, scanned, binary | Implemented, tested |
| Normalization (NFC, whitespace, control chars, hyphenation) and token-aware recursive chunking with page ranges and character offsets | Implemented, tested |
| Local embeddings (`BAAI/bge-small-en-v1.5`, 384-d, batched, lazy-loaded) stored in pgvector (HNSW, cosine) + generated `tsvector` (GIN) | Implemented, tested (fake embedder in tests, real model in compose run and evaluation) |
| `POST /search`: semantic, keyword (`ts_rank`), hybrid (RRF); owner + completed-status filter in SQL; optional cross-encoder reranker (off by default) | Implemented, tested; reranker tested with a fake only |
| `POST /ask`: retrieval, evidence threshold (no LLM call below it), token-budgeted context, untrusted-source prompt, citation validation, 503 on LLM failure | Implemented, tested with a mock LLM; see DIP2_HANDOFF.md for what ran against a real endpoint |
| `POST /documents/{id}/reprocess` (idempotent delete-then-rebuild of chunks) | Implemented, tested |
| Audit log for register, login, failed login, upload, delete | Implemented, tested |
| JSON logs, `X-Request-ID`, consistent error envelope, `/health`, `/health/live`, `/health/ready` | Implemented, tested |
| Password-protected Redis; secrets validated at startup, never logged | Implemented, tested |
| Rate limits (fixed window, Redis or in-memory): register/login per IP, login per email, upload/reprocess/search/ask per user; 429 + `Retry-After`; fails open if Redis is down | Implemented, tested (DIP3) |
| Request body limit before parsing (1 MiB JSON, upload limit + 64 KiB for `POST /documents`), 413 envelope | Implemented, tested (DIP3) |
| Security headers, HSTS in production, API docs off in production, production config checks (https CORS / LLM URL, no memory rate limiter, no DEBUG) | Implemented, tested (DIP3) |
| Prometheus `/metrics` (route-template labels, upload/search/ask/LLM/job/stage metrics), worker exporter on `WORKER_METRICS_PORT` | API metrics tested and run live; worker exporter **not verified** |
| Worker reliability: soft time limit -> clear failure, bounded redelivery, DB outage on finish -> retry, row lock against duplicate reprocess | Implemented, tested (DIP3) |
| GitHub Actions CI (`.github/workflows/ci.yml`) | Written and YAML-validated; **never run** (no remote) |
| OCR for scanned PDFs / images | **Not implemented** (scans fail with an explicit message) |
| Retrieval evaluation (Recall@k, Precision@k, MRR) on a small synthetic set | Script + results in [docs/retrieval.md](docs/retrieval.md#evaluation) |

A document that reaches `completed` has been verified, extracted, chunked, embedded and
indexed, and is searchable by its owner.

## Project structure

```
app/
  main.py                  application factory, middleware, routers
  cli.py                   python -m app.cli create-admin
  ai/                      provider protocols, embeddings, reranker, LLM client, factories
  api/routes/              auth, documents, search (/search, /ask), audit_logs, admin, health
  api/dependencies/        db session, auth guards, pagination, service wiring
  core/                    config, security, logging, request_context, middleware, errors
  db/                      base, session, models/, repositories/
  domain/                  enums, state_machine
  processing/              extraction, normalization, chunking (framework-free)
  schemas/                 Pydantic request/response models
  services/                auth, documents, search, answer (RAG), retrieval (RRF), prompts, ...
  storage/                 StorageService interface, LocalStorage, factory
  workers/                 celery_app, tasks, dispatcher, processing, pipeline, steps
alembic/                   env.py and versions/ (0001 initial schema, 0002 document_chunks)
tests/                     unit/, api/, integration/ (real PostgreSQL), fakes.py, fixtures/
scripts/generate_env.py    creates .env with random secrets
scripts/smoke_test.py      end-to-end check against a running stack (incl. search/ask)
scripts/evaluate_retrieval.py, scripts/calibrate_evidence_threshold.py
docs/                      architecture, document-processing, retrieval, rag, SECURITY, portfolio, adr/
```

## Local setup

Requirements: Docker with Compose v2 **or** Python 3.12 + [uv](https://docs.astral.sh/uv/)
with your own PostgreSQL 16 (pgvector) and Redis.

### 1. Create `.env`

```bash
python scripts/generate_env.py                       # random JWT_SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD
python scripts/generate_env.py --openai-key-file env # also import OPENAI_API_KEY from a file
python scripts/generate_env.py --openai-key-env OPENAI_API_KEY   # ...or from an env variable
```

The script copies `.env.example`, fills the three secrets with `secrets.token_urlsafe`
values (URL-safe, so they need no escaping in connection URLs), refuses to overwrite an
existing `.env` unless `--force` is given, and prints only the *names* of the keys it set.
The key file may contain `OPENAI_API_KEY=...` or just the key. `OPENAI_API_KEY` is only
needed for `POST /ask`; uploads, processing and `/search` work without it. `.env` and a
root-level file named `env` are git-ignored.

### 2a. Docker Compose (everything)

```bash
docker compose up --build -d
docker compose ps                       # postgres, redis healthy; migrate exited 0; api, worker healthy
curl http://localhost:8000/health/ready
uv run python scripts/smoke_test.py     # optional end-to-end check (stdlib only)
```

Services: `postgres`, `redis` (`--requirepass`), `migrate` (runs `alembic upgrade head`
once), `api` (port `API_PORT`, default 8000), `worker`. Compose sets `POSTGRES_HOST` /
`REDIS_HOST` to the service names and refuses to start if `JWT_SECRET_KEY`,
`POSTGRES_PASSWORD` or `REDIS_PASSWORD` is empty. API and worker share the
`storage_data` volume and the `model_cache` volume (`HF_HOME`), into which the embedding
model (~130 MB) is downloaded on first use; the first document therefore takes longer.
Set `HF_HUB_OFFLINE=1` once the cache is populated (or pre-seeded) if the containers have
no internet access. Postgres and Redis are not published to the host.

### 2b. Python processes on the host

```bash
uv sync                                 # .venv with app + dev dependencies
# .env: POSTGRES_HOST/PORT and REDIS_HOST/PORT point at your services,
# or set DATABASE_URL / REDIS_URL explicitly
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --no-access-log
uv run celery -A app.workers.celery_app:celery_app worker --loglevel=INFO   # second terminal
```

Create an administrator (password from `ADMIN_PASSWORD` or an interactive prompt):

```bash
uv run python -m app.cli create-admin --email admin@example.com
docker compose exec api python -m app.cli create-admin --email admin@example.com
```

### Windows notes

- Use Docker Desktop (WSL 2 backend) for option 2a; commands are the same in PowerShell.
- Run scripts with `uv run python scripts\generate_env.py ...` (or `py -3.12 ...`). On
  Windows the script cannot set POSIX `0600` permissions; keep `.env` in your user folder.
- Celery's default prefork pool is not supported on Windows; add `--pool=solo` to the
  worker command when running it on the host.
- PowerShell syntax for test variables: `$env:TEST_DATABASE_URL = "postgresql+psycopg://..."`.
- DIP3 ran the test suite on Windows 11 with Python 3.12 against a local PostgreSQL 16 +
  pgvector 0.6.2 (no Docker). POSIX-only tests (file mode `0600`, symlinks without
  privilege) are skipped there. Docker Desktop and the Celery worker were not run.

## Environment variables

All names below appear in `.env.example`; values there are placeholders.

| Variable | Default | Notes |
| --- | --- | --- |
| `APP_NAME` | `Document Intelligence Platform` | OpenAPI title |
| `APP_ENV` | `development` | `development` / `test` / `production` |
| `DEBUG` | `false` | must be `false` when `APP_ENV=production` |
| `LOG_LEVEL` | `INFO` | |
| `API_PORT` | `8000` | compose host port |
| `JWT_SECRET_KEY` | *(required)* | >= 32 chars; placeholders rejected |
| `JWT_ALGORITHM` | `HS256` | HS256/HS384/HS512 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | 1-1440 |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` / `POSTGRES_USER` | `localhost` / `5432` / `dip` / `dip` | |
| `POSTGRES_PASSWORD` | *(required outside `APP_ENV=test`)* | unless `DATABASE_URL` is set |
| `DATABASE_URL` | built from `POSTGRES_*` | optional full override |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | `localhost` / `6379` / `0` | |
| `REDIS_PASSWORD` | *(required outside `APP_ENV=test`)* | unless `REDIS_URL` is set |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | built from `REDIS_*` | optional overrides |
| `STORAGE_BACKEND` | `local` | only `local` exists; anything else fails at startup |
| `STORAGE_PATH` | `./storage_data` | `/data/storage` in containers |
| `MAX_UPLOAD_SIZE_BYTES` | `10485760` | 413 above this |
| `ALLOWED_EXTENSIONS` / `ALLOWED_CONTENT_TYPES` | pdf,docx,txt / matching types | comma separated |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | `*` rejected |
| `OPENAI_API_KEY` | unset | only needed for `/ask` (`LLM_PROVIDER=openai`) |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` | `sentence-transformers` / `BAAI/bge-small-en-v1.5` | only provider: sentence-transformers |
| `EMBEDDING_DIMENSION` | `384` | must match the `vector(384)` column; verified against the loaded model |
| `EMBEDDING_BATCH_SIZE` | `32` | passages per embedding call |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `400` / `60` | tokens of the embedding tokenizer |
| `MAX_CHUNKS_PER_DOCUMENT` | `1000` | larger documents fail with a clear reason |
| `HF_HUB_OFFLINE` | `0` | compose; `1` = use only the cached model |
| `TOP_K` / `MAX_TOP_K` / `CANDIDATE_K` | `5` / `20` / `40` | results, upper bound, per-list candidates for hybrid |
| `MAX_QUERY_LENGTH` | `1000` | characters |
| `MIN_EVIDENCE_SIMILARITY` | `0.48` | cosine threshold for `/ask` evidence ([docs/rag.md](docs/rag.md#threshold-calibration)) |
| `RERANKING_ENABLED` / `RERANKER_MODEL` / `RERANK_TOP_K` | `false` / `cross-encoder/ms-marco-MiniLM-L-6-v2` / `20` | optional cross-encoder |
| `LLM_PROVIDER` | `openai` | `openai` (any OpenAI-compatible endpoint) or `none` |
| `LLM_MODEL` / `LLM_BASE_URL` | `gpt-4o-mini` / `https://api.openai.com/v1` | |
| `LLM_TIMEOUT_SECONDS` | `30` | hard HTTP timeout |
| `MAX_CONTEXT_TOKENS` | `3000` | approximate token budget for retrieved context |
| `TEST_DATABASE_URL` / `TEST_REDIS_URL` | - | tests only (commented out in `.env.example`) |
| `API_DOCS_ENABLED` | unset (on, off in production) | Swagger/ReDoc/OpenAPI |
| `MAX_REQUEST_BODY_BYTES` / `UPLOAD_BODY_OVERHEAD_BYTES` | `1048576` / `65536` | body limits enforced before parsing |
| `SECURITY_HEADERS_ENABLED` | `true` | nosniff, frame deny, no-referrer, CORP; HSTS only in production |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_BACKEND` | `true` / `redis` | `memory` is per process and rejected in production |
| `RATE_LIMIT_REGISTER` / `_LOGIN` / `_LOGIN_PER_EMAIL` / `_UPLOAD` / `_SEARCH` / `_ASK` / `_REPROCESS` | `5/minute` / `10/minute` / `5/minute` / `30/minute` / `60/minute` / `20/minute` / `10/minute` | format `N/second`, `N/minute`, `N/hour` or `N/day` |
| `METRICS_ENABLED` / `WORKER_METRICS_PORT` | `true` / unset | `/metrics` on the API; worker exporter port (compose: 9100, internal only) |
| `CELERY_TASK_SOFT_TIME_LIMIT` / `CELERY_TASK_TIME_LIMIT` | `240` / `300` | seconds; soft must be lower |

Further tunables with safe defaults (not in `.env.example`): `DB_POOL_SIZE`,
`DB_MAX_OVERFLOW`, `CELERY_TASK_MAX_RETRIES`, `CELERY_RETRY_BACKOFF_SECONDS`,
`UPLOAD_CHUNK_SIZE_BYTES`, `JWT_ISSUER`, `EMBEDDING_DEVICE`, `EMBEDDING_QUERY_INSTRUCTION`,
`MAX_DOCX_UNCOMPRESSED_BYTES`, `LLM_MAX_OUTPUT_TOKENS`, `LLM_TEMPERATURE`, and the DIP1
SDK-adapter settings `OPENAI_CHAT_MODEL`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_TIMEOUT_SECONDS`
(not used by `/ask`, which reads `LLM_*`).

Invalid configuration stops startup with a message such as
`SettingsError: Invalid configuration: JWT_SECRET_KEY is required but not set`; messages
name variables, never values.

## Migrations

```bash
uv run alembic upgrade head
uv run alembic check                    # must report "No new upgrade operations detected."
uv run alembic revision -m "describe change"   # then edit the generated file by hand
```

Revision `0001` creates the four tables and ENUM types and enables the `vector`
extension. Revision `0002` adds `document_chunks` (`vector(384)` with an HNSW cosine
index, generated `tsvector` with a GIN index, unique `(document_id, chunk_index)`,
cascading deletes) and `document_processing_jobs.stage`. Never edit an applied
revision; add a new one.

## Tests and quality checks

Unit tests run without any services: `uv run pytest` with no `TEST_DATABASE_URL` runs
the unit tests and skips the database-backed API/integration tests (DIP3 measurement:
216 passed, 117 skipped). The full suite needs a disposable PostgreSQL + pgvector
database (it runs the Alembic migrations and truncates tables after each test). Celery is replaced by a recording fake, the embedding
model by a deterministic hashing embedder and the LLM by a mock, so neither Redis, model
downloads nor network access are required. Two readiness tests
additionally run when `TEST_REDIS_URL` points at a Redis (one needs a password in it).

```bash
docker run -d --name dip-test-db -e POSTGRES_USER=dip -e POSTGRES_PASSWORD=dip \
  -e POSTGRES_DB=dip_test -p 5433:5432 pgvector/pgvector:pg16
export TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test
export TEST_REDIS_URL='redis://:<redis-password>@localhost:6380/0'   # optional
uv run pytest --cov=app
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Last recorded run (DIP3, Windows, PostgreSQL 16 + pgvector 0.6.2): 330 passed, 3 skipped,
95% coverage. Details: [docs/testing.md](docs/testing.md) and [DIP3_HANDOFF.md](DIP3_HANDOFF.md).
CI runs the same commands: [.github/workflows/ci.yml](.github/workflows/ci.yml).

## Using search and ask

PowerShell users: replace `\` line continuations with backticks or put each command on
one line. Outputs are not shown here; response shapes are in
[docs/retrieval.md](docs/retrieval.md#api) and [docs/rag.md](docs/rag.md#response).

```bash
BASE=http://localhost:8000
curl -s -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-long-enough-password"}'
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-long-enough-password"}' | jq -r .access_token)

# upload, then poll until status is "completed" (job.stage shows the current step)
DOC=$(curl -s -X POST $BASE/documents -H "Authorization: Bearer $TOKEN" \
  -F "file=@policy.pdf;type=application/pdf" | jq -r .id)
curl -s $BASE/documents/$DOC/status -H "Authorization: Bearer $TOKEN"

# search: mode = semantic | keyword | hybrid (default); optional document_id
curl -s -X POST $BASE/search -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"refund window","mode":"hybrid","top_k":5}'

# ask: grounded answer with citations (needs OPENAI_API_KEY; otherwise 503)
curl -s -X POST $BASE/ask -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"How many days do customers have to return items?"}'

# reprocess a completed or failed document
curl -s -X POST $BASE/documents/$DOC/reprocess -H "Authorization: Bearer $TOKEN"
```

## API documentation

With the API running: Swagger UI at `/docs` (use **Authorize** with email as username),
ReDoc at `/redoc`, schema at `/openapi.json`.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health`, `/health/live` | - | liveness |
| GET | `/health/ready` | - | PostgreSQL + Redis readiness (503 if down) |
| POST | `/auth/register` | - | create user (role `user`) |
| POST | `/auth/login` | - | JSON login -> JWT |
| POST | `/auth/token` | - | OAuth2 form login -> JWT (Swagger) |
| GET | `/auth/me` | user | current user |
| POST | `/documents` | user | multipart upload, queues processing |
| GET | `/documents` | user | `page`, `page_size` (max 100) |
| GET | `/documents/{id}` | user | metadata |
| GET | `/documents/{id}/status` | user | status + latest job (with `stage`) + `chunk_count` |
| POST | `/documents/{id}/reprocess` | user | queue a new job for a completed/failed document (202; 409 while busy) |
| DELETE | `/documents/{id}` | user | delete record, jobs, chunks and file (204) |
| POST | `/search` | user | semantic / keyword / hybrid retrieval over own completed documents |
| POST | `/ask` | user | grounded answer with citations; 503 if the LLM is unavailable |
| GET | `/audit-logs/me` | user | own audit entries |
| GET | `/admin/users` | admin | all users |
| GET | `/admin/audit-logs` | admin | all audit entries, filters `user_id`, `action` |

Errors always look like
`{"error": {"code": "not_found", "message": "Document not found", "request_id": "..."}}`.

## Security considerations

- Argon2id password hashing; generic login error; dummy hash on unknown email.
- Short-lived JWTs with issuer, type and required-claim checks; role and active flag
  re-read from the database on every request.
- Per-owner queries; foreign documents return 404, not 403.
- Upload validation: extension/content-type allow-list, magic bytes, size limit while
  streaming, sanitised display name, server-generated storage keys, traversal guard.
- Secrets only from the environment, as `SecretStr`; startup fails on missing or
  placeholder secrets; `.env`/`env` git-ignored; log redaction of sensitive keys.
- Redis requires a password; Postgres/Redis are not exposed by compose.
- CORS restricted to configured origins; containers run as a non-root user.
- Retrieval: owner and completed-status filters inside every chunk query; `/ask` prompt
  keeps retrieved text in an escaped `<untrusted_sources>` block; citations restricted to
  sent sources; no secrets or document text in logs. Details: [docs/SECURITY.md](docs/SECURITY.md).
- DIP3: rate limits, body limits before parsing, security headers, API docs off in
  production, stricter production config validation, compose `cap_drop: [ALL]` +
  `no-new-privileges`.

More: [architecture](docs/architecture.md), [testing](docs/testing.md),
[observability](docs/observability.md), [performance](docs/performance.md),
[deployment](docs/deployment.md), [portfolio notes](docs/portfolio.md).

## Roadmap

- **DIP2** - implemented except OCR: [DIP2_HANDOFF.md](DIP2_HANDOFF.md).
- **DIP3** - implemented locally (rate limiting, metrics, hardening, CI workflow, docs);
  Docker/CI verification outstanding: [DIP3_HANDOFF.md](DIP3_HANDOFF.md).
- **Later** - tracing (OpenTelemetry), image scanning and digest pinning, a stuck-job
  reaper, OCR, refresh tokens / revocation.

## Known limitations

- No OCR: scanned PDFs fail with an explicit message.
- Retrieval quality was measured only on 18 synthetic queries over 6 short documents;
  latency, throughput and index behaviour at scale are not measured.
- The `/ask` evidence threshold (0.48) was calibrated on that small set only.
- Citations show which retrieved passage the model pointed at; there is no entailment check.
- Body size is now limited before parsing, but upload rate limiting runs after the
  multipart body (at most the upload limit + 64 KiB) has been received.
- DOCX validation only checks the ZIP signature.
- If the broker is down at upload time the document is marked `failed`; it can be
  retried with `POST /documents/{id}/reprocess`.
- Rate limits are fixed-window (bursts of up to 2x at window edges) and fail open when
  Redis is unavailable. No account lockout, refresh tokens or token revocation.
- If the very last processing attempt cannot write its result to the database, the job
  stays `processing` (no reaper yet); `POST /documents/{id}/reprocess` returns 409 for it.
- No tracing; worker metrics exporter not verified.
- The Redis password is passed to `redis-server` as a command-line argument (visible to
  anyone who can run `docker inspect` on the host).
- Local filesystem storage only; API and worker must share the volume.
- Performance and scalability are not measured yet ([docs/performance.md](docs/performance.md)).
