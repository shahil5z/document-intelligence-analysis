# Document Intelligence Platform

Backend that ingests PDF, DOCX and TXT documents, turns them into searchable chunks
with local embeddings, and answers questions with citations that point at the passages
that were actually retrieved. Every query is scoped to the document owner inside SQL.

Built in three stages and consolidated on the `final` branch:

| Stage | Scope |
| --- | --- |
| **DIP1** | Auth (JWT, Argon2id, roles), uploads + validation, local storage, Celery job pipeline with an explicit state machine, audit log, JSON logs, Docker |
| **DIP2** | Text extraction, normalization, token-aware chunking, local embeddings in pgvector, semantic / keyword / hybrid (RRF) search, `/ask` with validated citations |
| **DIP3 + final** | Rate limiting (fail-closed for credentials), body limits before parsing, security headers, Prometheus metrics (API + worker), worker reliability (bounded retries, terminal failure, stale-job reconciler), pinned images, CI workflow, smoke test, benchmark |

What was verified, with numbers, is in [FINAL_PROJECT_REPORT.md](FINAL_PROJECT_REPORT.md).
OCR is **not implemented**: scanned PDFs fail with an explicit message.

## Architecture

```mermaid
flowchart LR
    client[Client] --> api[FastAPI API]
    api --> pg[(PostgreSQL 16 + pgvector)]
    api --> redis[(Redis: broker + rate limits)]
    api --> storage[[File storage volume]]
    worker[Celery worker + beat] --> redis
    worker -->|chunks + vectors| pg
    worker --> storage
    worker --> model[[bge-small-en-v1.5, local]]
    api --> model
    api -->|/ask only| llm[OpenAI-compatible LLM]
```

Routes -> services (transaction boundaries) -> repositories (owner-scoped queries) ->
SQLAlchemy models. An upload creates a processing job; the worker runs integrity check
-> extract -> normalize -> chunk -> embed -> index. Details:
[docs/architecture.md](docs/architecture.md), decisions in [docs/adr/](docs/adr).

Stack: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (sync, psycopg 3), Alembic,
PostgreSQL 16 + pgvector (HNSW) + full-text search, Redis 7, Celery 5, PyJWT, pwdlib
(Argon2id), pypdf, python-docx, sentence-transformers (CPU torch), httpx2, uv, pytest,
ruff, mypy (strict), Docker Compose.

## Quick start on Windows

Two routes. Both start from a clone of the repository in PowerShell 7 and a `.env`.

### Step 1 - `.env` (both routes)

```powershell
py -3.12 scripts\generate_env.py                                   # new .env with random secrets
py -3.12 scripts\generate_env.py --openai-key-file env             # ...and import OPENAI_API_KEY from a file
py -3.12 scripts\generate_env.py --merge --dry-run                 # existing .env: list keys that are missing
py -3.12 scripts\generate_env.py --merge                           # ...append them (existing values untouched, .env.bak written)
```

`generate_env.py` uses only the standard library, prints key **names** only, never
values, refuses to overwrite an existing `.env` without `--force`, and with `--merge`
appends missing keys from `.env.example` (generating missing secrets) without changing
any existing line. `.env`, `env` and `.env.bak` are git-ignored and excluded from the
Docker build context.

### Route A - Docker Desktop (recommended)

Requirements: Docker Desktop with the WSL 2 backend.

```powershell
docker compose up --build -d
docker compose ps                     # postgres, redis, api, worker healthy; migrate exited 0
Invoke-RestMethod http://localhost:8000/health/ready
uv run python scripts/smoke_test.py   # end-to-end check (stdlib only; /ask expected 503 without a key)
```

Services: `postgres`,
`redis` (password from a 0600 config file, not on the command line), `migrate`
(`alembic upgrade head`, once), `api` (host port `API_PORT`), `worker` (Celery worker
with embedded beat for the stale-job reconciler; metrics on 9100 inside the network).
Postgres, Redis and the worker exporter are not published to the host.

The embedding model (~130 MB) is downloaded into the `model_cache` volume on first use,
so the first document takes longer. If the containers have no internet access, pre-seed
the volume and set `HF_HUB_OFFLINE=1` ([docs/deployment.md](docs/deployment.md#offline-model-cache)).

### Route B - without Docker

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL 16 with the
pgvector extension (>= 0.5.0, 0.8+ recommended), and a Redis 6+ with a password
(for example Redis in WSL, or Memurai on Windows).

```powershell
uv sync
# .env: POSTGRES_HOST/PORT/USER/PASSWORD/DB and REDIS_HOST/PORT/PASSWORD point at your services
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000 --no-access-log
# second terminal: Celery's prefork pool does not work on Windows, use solo
uv run celery -A app.workers.celery_app:celery_app worker -B --pool=solo --loglevel=INFO
```

Create an administrator (password from `ADMIN_PASSWORD` or a prompt):

```powershell
uv run python -m app.cli create-admin --email admin@example.com
docker compose exec api python -m app.cli create-admin --email admin@example.com
```

## Environment variables

Only three values are **mandatory**; everything else has a safe default. All names are
in [.env.example](.env.example) with comments. Invalid configuration stops startup with
a message that names the variable, never the value.

| Mandatory | Why |
| --- | --- |
| `JWT_SECRET_KEY` | >= 32 characters; placeholders are rejected |
| `POSTGRES_PASSWORD` | unless `DATABASE_URL` is set (not required when `APP_ENV=test`) |
| `REDIS_PASSWORD` | unless `REDIS_URL` is set (not required when `APP_ENV=test`) |

| Needed for one feature | Default | Notes |
| --- | --- | --- |
| `OPENAI_API_KEY` | unset | only `/ask`. Without it `/ask` returns 503 once evidence is found; upload, processing and `/search` work |

| Optional | Default | Notes |
| --- | --- | --- |
| `APP_NAME` / `APP_ENV` / `DEBUG` / `LOG_LEVEL` / `API_PORT` | `Document Intelligence Platform` / `development` / `false` / `INFO` / `8000` | `APP_ENV=production` enables stricter checks |
| `JWT_ALGORITHM` / `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `HS256` / `30` | HS256/384/512; 1-1440 minutes |
| `POSTGRES_HOST` / `_PORT` / `_DB` / `_USER`, `DATABASE_URL` | `localhost` / `5432` / `dip` / `dip` | compose sets host/port itself |
| `REDIS_HOST` / `_PORT` / `_DB`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | `localhost` / `6379` / `0` | URLs built from the parts unless set |
| `STORAGE_BACKEND` / `STORAGE_PATH` | `local` / `./storage_data` | only `local` exists |
| `MAX_UPLOAD_SIZE_BYTES` | `10485760` | 413 above this |
| `ALLOWED_EXTENSIONS` / `ALLOWED_CONTENT_TYPES` | pdf,docx,txt / matching MIME types | comma separated |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | `*` rejected |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` / `EMBEDDING_BATCH_SIZE` | `sentence-transformers` / `BAAI/bge-small-en-v1.5` / `384` / `32` | dimension must match the `vector(384)` column |
| `TORCH_NUM_THREADS` | `2` | PyTorch threads per process; `0` = one per core (much slower when processes share the CPU, see [docs/performance.md](docs/performance.md)) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` / `MAX_CHUNKS_PER_DOCUMENT` | `400` / `60` / `1000` | tokens of the embedding tokenizer |
| `HF_HUB_OFFLINE` | `0` | `1` = use only the cached model |
| `TOP_K` / `MAX_TOP_K` / `CANDIDATE_K` / `MAX_QUERY_LENGTH` | `5` / `20` / `40` / `1000` | |
| `MIN_EVIDENCE_SIMILARITY` | `0.48` | below it `/ask` answers "insufficient evidence" without calling the LLM |
| `RERANKING_ENABLED` / `RERANKER_MODEL` / `RERANK_TOP_K` | `false` / `cross-encoder/ms-marco-MiniLM-L-6-v2` / `20` | optional cross-encoder |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` | `openai` / `gpt-4o-mini` / `https://api.openai.com/v1` | any OpenAI-compatible endpoint; `none` disables `/ask` |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_OUTPUT_TOKENS` / `LLM_TEMPERATURE` / `MAX_CONTEXT_TOKENS` | `30` / `700` / `0` / `3000` | |
| `API_DOCS_ENABLED` | empty (on; off in production) | `/docs`, `/redoc`, `/openapi.json` |
| `MAX_REQUEST_BODY_BYTES` / `UPLOAD_BODY_OVERHEAD_BYTES` | `1048576` / `65536` | enforced before the body is parsed |
| `SECURITY_HEADERS_ENABLED` | `true` | HSTS only in production |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_BACKEND` | `true` / `redis` | `memory` is per process, rejected in production |
| `RATE_LIMIT_REGISTER` / `_LOGIN` / `_LOGIN_PER_EMAIL` / `_UPLOAD` / `_SEARCH` / `_ASK` / `_REPROCESS` | `5/minute` / `10/minute` / `5/minute` / `30/minute` / `60/minute` / `20/minute` / `10/minute` | `N/second\|minute\|hour\|day` |
| `METRICS_ENABLED` / `WORKER_METRICS_PORT` | `true` / empty | compose sets the worker port to 9100 |
| `CELERY_TASK_SOFT_TIME_LIMIT` / `CELERY_TASK_TIME_LIMIT` | `240` / `300` | seconds; soft < hard |
| `STALE_JOB_TIMEOUT_SECONDS` / `STALE_JOB_CHECK_INTERVAL_SECONDS` | `900` / `300` | reconciler; timeout must exceed the hard limit; interval `0` = not scheduled |
| `TEST_DATABASE_URL` / `TEST_REDIS_URL` | - | test suite only |

Further tunables without `.env.example` entries: `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
`CELERY_TASK_MAX_RETRIES`, `CELERY_RETRY_BACKOFF_SECONDS`, `UPLOAD_CHUNK_SIZE_BYTES`,
`JWT_ISSUER`, `EMBEDDING_DEVICE`, `EMBEDDING_QUERY_INSTRUCTION`,
`MAX_DOCX_UNCOMPRESSED_BYTES`, and the DIP1 SDK-adapter settings `OPENAI_CHAT_MODEL`,
`OPENAI_EMBEDDING_MODEL`, `OPENAI_TIMEOUT_SECONDS` (legacy; not used by `/ask` or the
pipeline, which read `LLM_*` and `EMBEDDING_*`).

## Using the API

Swagger UI at `/docs` (Authorize with the email as username), ReDoc at `/redoc`.

### curl (Linux / macOS / Git Bash)

```bash
BASE=http://localhost:8000
curl -s -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-long-enough-password"}'
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-long-enough-password"}' | jq -r .access_token)
DOC=$(curl -s -X POST $BASE/documents -H "Authorization: Bearer $TOKEN" \
  -F "file=@policy.pdf;type=application/pdf" | jq -r .id)
curl -s $BASE/documents/$DOC/status -H "Authorization: Bearer $TOKEN"    # poll until "completed"
curl -s -X POST $BASE/search -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"refund window","mode":"hybrid","top_k":5}'
curl -s -X POST $BASE/ask -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"How many days do customers have to return items?"}'
curl -s -X POST $BASE/documents/$DOC/reprocess -H "Authorization: Bearer $TOKEN"
```

### PowerShell 7

```powershell
$base = "http://localhost:8000"
$cred = @{ email = "me@example.com"; password = "a-long-enough-password" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/auth/register" -ContentType application/json -Body $cred
$token = (Invoke-RestMethod -Method Post "$base/auth/login" -ContentType application/json -Body $cred).access_token
$h = @{ Authorization = "Bearer $token" }
# curl.exe (ships with Windows) sets the part content type; Invoke-RestMethod -Form would send octet-stream (415)
$doc = curl.exe -s -X POST "$base/documents" -H "Authorization: Bearer $token" -F "file=@policy.pdf;type=application/pdf" | ConvertFrom-Json
Invoke-RestMethod "$base/documents/$($doc.id)/status" -Headers $h
$q = @{ query = "refund window"; mode = "hybrid"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/search" -Headers $h -ContentType application/json -Body $q
$a = @{ question = "How many days do customers have to return items?" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/ask" -Headers $h -ContentType application/json -Body $a
```

The full 26-step manual checklist (including a safe procedure for a real OpenAI key)
is in [docs/manual-testing.md](docs/manual-testing.md).

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health`, `/health/live` | - | liveness |
| GET | `/health/ready` | - | PostgreSQL, pgvector version, Redis (503 if any fails) |
| POST | `/auth/register`, `/auth/login`, `/auth/token` | - | register; JSON login; OAuth2 form login |
| GET | `/auth/me` | user | current user |
| POST | `/documents` | user | multipart upload (201), queues processing |
| GET | `/documents`, `/documents/{id}`, `/documents/{id}/status` | user | list (paginated), metadata, status + latest job + chunk count |
| POST | `/documents/{id}/reprocess` | user | new job for a completed/failed document (202; 409 while busy) |
| DELETE | `/documents/{id}` | user | delete record, jobs, chunks, file (204) |
| POST | `/search` | user | semantic / keyword / hybrid over own completed documents |
| POST | `/ask` | user | grounded answer with citations; insufficient-evidence answer without an LLM call; 503 if the LLM fails |
| GET | `/audit-logs/me` | user | own audit entries |
| GET | `/admin/users`, `/admin/audit-logs` | admin | all users / audit entries |
| GET | `/metrics` | - | Prometheus (internal network only) |

Errors: `{"error": {"code": "not_found", "message": "Document not found", "request_id": "..."}}`.
Other users' documents return 404, never 403.

## Tests and quality checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app tests scripts
docker run -d --name dip-test-db -e POSTGRES_USER=dip -e POSTGRES_PASSWORD=dip \
  -e POSTGRES_DB=dip_test -p 5433:5432 pgvector/pgvector:pg16
export TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test
export TEST_REDIS_URL='redis://:<redis-password>@localhost:6380/0'   # optional, real-Redis tests
uv run pytest --cov=app
```

PowerShell: `$env:TEST_DATABASE_URL = "postgresql+psycopg://dip:dip@localhost:5433/dip_test"`.
Without `TEST_DATABASE_URL` the database-backed tests skip. Celery, the embedding model
and the LLM are replaced by fakes in the suite, so no network is needed. Current numbers
and what each layer covers: [docs/testing.md](docs/testing.md).

End to end against a running stack: `uv run python scripts/smoke_test.py --base-url
http://localhost:8000` (add `--ask-expect answer` with an LLM configured, `--real-llm`
for an explicit real-model check, `--check-rate-limit` for the login limit). For a
key-free `/ask` path, `docker-compose.stub-llm.yml` adds a local OpenAI-compatible stub.

## Migrations

```bash
uv run alembic upgrade head
uv run alembic check          # "No new upgrade operations detected."
```

`0001` creates users, documents, jobs, audit logs and enables `vector`; `0002` adds
`document_chunks` (`vector(384)` + HNSW cosine index, generated `tsvector` + GIN) and
`document_processing_jobs.stage`. Never edit an applied revision.

## Documentation

[architecture](docs/architecture.md) · [document processing](docs/document-processing.md)
· [retrieval](docs/retrieval.md) · [RAG](docs/rag.md) · [security](docs/SECURITY.md) ·
[testing](docs/testing.md) · [observability](docs/observability.md) ·
[performance](docs/performance.md) · [deployment](docs/deployment.md) ·
[manual testing](docs/manual-testing.md) · [portfolio notes](docs/portfolio.md) ·
[final report](FINAL_PROJECT_REPORT.md)

## Known limitations

- No OCR; scanned PDFs and images fail with an explicit message. DOCX extraction reads
  body paragraphs and tables only (no headers/footers, footnotes, comments, text boxes;
  no legacy `.doc`; no page numbers).
- Retrieval quality was measured on 18 synthetic queries over 6 short documents; the
  `/ask` evidence threshold (0.48) was calibrated on that set only.
- Citations show which retrieved passage the model pointed at; no entailment check.
- Fixed-window rate limits (bursts up to 2x at window edges); no account lockout,
  refresh tokens or token revocation. The upload rate limit is checked after the body
  (at most the upload limit + 64 KiB) has been received.
- `/metrics` and the worker exporter are unauthenticated; keep them internal.
- Local filesystem storage only; API and worker must share the volume.
- The LLM client sends `max_tokens` and `temperature`; some reasoning models reject these.
- Performance was measured once, on one machine, with small documents
  ([docs/performance.md](docs/performance.md)); no load or scale testing.
