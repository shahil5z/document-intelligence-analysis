# Document Intelligence & Analysis

> Repository, package, Docker service and database names keep the original
> `document-intelligence-platform` / `dip` slugs; only user-facing text was renamed.

## 1. Overview

A multi-tenant document question-answering system. Users upload PDF, DOCX and TXT
files; a background worker extracts, chunks and embeds the text locally; users search
their own documents (semantic, keyword or hybrid) and ask questions that are answered
only from retrieved passages, with citations that point at those passages. Every query
is scoped to the document owner inside SQL.

- **Backend**: FastAPI + PostgreSQL/pgvector + Redis + Celery (DIP1-DIP3, `final`).
- **Frontend**: Next.js App Router in [`frontend/`](frontend) (production phase).
- **Production setup**: `docker-compose.prod.yml` + Caddy for a single Oracle Cloud
  Always Free Ampere VM, frontend on Vercel, ops scripts, CI/CD workflows.

- **Demo mode**: "Try the demo" creates an ephemeral account (1 PDF, 3 questions,
  deleted after 24 hours) that can be converted into a free account in place
  ([docs/demo-mode.md](docs/demo-mode.md)).
- **UI**: dark by default with a persisted light/dark toggle (applied before first
  paint), sidebar on desktop and bottom navigation on mobile, chat-style Ask with
  clickable `[n]` citation chips, upload stepper, toasts, Impressum/Privacy templates.

What was verified, with numbers, is in [FINAL_PROJECT_REPORT.md](FINAL_PROJECT_REPORT.md)
(the single source of truth). OCR is **not implemented**: scanned PDFs fail with an
explicit message.

## 2. Screenshots

Taken by the Playwright suite against the local production-like stack
(`docker-compose.prod.yml` behind Caddy with a local CA; `/ask` answered by the local
**stub** LLM, not OpenAI).

| | |
| --- | --- |
| Landing ![landing](docs/screenshots/landing.png) | Dashboard ![dashboard](docs/screenshots/dashboard.png) |
| Upload ![upload](docs/screenshots/upload.png) | Documents ![documents](docs/screenshots/documents.png) |
| Document detail ![detail](docs/screenshots/document-detail.png) | Search ![search](docs/screenshots/search.png) |
| Ask (stub LLM) ![ask](docs/screenshots/ask.png) | Architecture ![architecture](docs/screenshots/architecture.png) |
| Mobile ![mobile](docs/screenshots/mobile-dashboard.png) | |

UX round (dark default and light theme, desktop 1366px and mobile 375px):

| Dark | Light |
| --- | --- |
| ![landing dark](docs/screenshots/landing-desktop-dark.png) | ![landing light](docs/screenshots/landing-desktop-light.png) |
| ![ask dark](docs/screenshots/ask-citations-dark.png) | ![ask light](docs/screenshots/ask-citations-light.png) |
| ![dashboard dark](docs/screenshots/dashboard-desktop-dark.png) | ![dashboard light](docs/screenshots/dashboard-desktop-light.png) |
| ![demo modal dark](docs/screenshots/demo-limit-modal-dark.png) | ![demo modal light](docs/screenshots/demo-limit-modal-light.png) |
| ![landing mobile dark](docs/screenshots/landing-mobile-dark.png) | ![landing mobile light](docs/screenshots/landing-mobile-light.png) |
| ![ask mobile dark](docs/screenshots/ask-mobile-dark.png) | ![ask mobile light](docs/screenshots/ask-mobile-light.png) |

Also: `login-*`, `impressum-*`, `dashboard-mobile-*`, `demo-upload-ready-dark.png`.

## 3. Live demo

**Not deployed yet.** There is no public URL. Everything needed is configured
(compose file, Caddy, scripts, workflows, docs); the remaining steps need the owner's
Oracle Cloud, Vercel and GitHub accounts: [MANUAL_DEPLOYMENT_CHECKLIST.md](MANUAL_DEPLOYMENT_CHECKLIST.md).

| | URL |
| --- | --- |
| Frontend (Vercel) | not deployed |
| API (Oracle VM) | not deployed |

## 4. Architecture

```mermaid
flowchart LR
    user[Browser] -->|pages, /api/auth, /api/proxy| next[Next.js BFF<br/>HttpOnly session cookie]
    next -->|Bearer JWT| api[FastAPI API]
    user -->|direct upload, 300 s upload-only token| api
    api --> pg[(PostgreSQL 16 + pgvector)]
    api --> redis[(Redis: broker + rate limits)]
    api --> files[[Storage: volume or OCI Object Storage]]
    worker[Celery worker] --> redis
    worker -->|chunks + vectors| pg
    worker --> files
    beat[Celery beat] -->|stale-job reconciler| redis
    worker --> model[[bge-small-en-v1.5, local CPU]]
    api --> model
    api -->|/ask only| llm[OpenAI-compatible LLM]
```

Routes -> services (transaction boundaries) -> repositories (owner-scoped queries) ->
SQLAlchemy models. An upload creates a processing job; the worker runs integrity check
-> extract -> normalize -> chunk -> embed -> index. Details:
[docs/architecture.md](docs/architecture.md), decisions in [docs/adr/](docs/adr).

## 5. Features

- Accounts: register/login (Argon2id, JWT), roles, admin endpoints, audit log.
- Uploads: PDF/DOCX/TXT up to 10 MB, extension + MIME + magic-byte checks, per-user
  duplicate detection; storage on a local volume, any S3-compatible service, or OCI
  Object Storage.
- Processing: Celery pipeline with an explicit state machine, bounded retries, terminal
  failure, stale-job reconciler; token-aware chunking; local 384-d embeddings.
- Retrieval: semantic (HNSW), keyword (PostgreSQL full-text) and hybrid (RRF), optional
  cross-encoder reranking.
- `/ask`: grounded answers with validated `[S#]` citations; "insufficient evidence"
  without calling the LLM when retrieval is weak; works (503 "not configured") without
  an OpenAI key.
- Hardening: rate limits (fail-closed for credentials), body limits before parsing,
  security headers, Prometheus metrics, JSON logs without secrets or document text.
- Frontend: landing, login, register, dashboard, upload (progress bar), documents list,
  document detail (status, job, reprocess, delete), search, ask with citations,
  architecture page, settings/logout; skeletons, empty states, friendly errors, mobile
  layout.

API endpoints:

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health`, `/health/live` | - | liveness |
| GET | `/health/ready` | - | PostgreSQL, pgvector version, Redis (503 if any fails) |
| POST | `/auth/register`, `/auth/login`, `/auth/token` | - | register; JSON login; OAuth2 form login |
| GET | `/auth/me` | user | current user |
| POST | `/auth/upload-token` | user | 300 s token valid only for `POST /documents` (browser direct upload) |
| GET | `/documents/upload-policy` | user | allowed extensions/types and the size limit |
| POST | `/documents` | user or upload token | multipart upload (201), queues processing |
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

## 6. Stack

Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (sync, psycopg 3), Alembic,
PostgreSQL 16 + pgvector (HNSW) + full-text search, Redis 7, Celery 5, PyJWT, pwdlib
(Argon2id), pypdf, python-docx, sentence-transformers (CPU torch), boto3, httpx2,
gunicorn + uvicorn-worker, uv, pytest, ruff, mypy (strict).
Frontend: Next.js 16 (App Router), React, TypeScript, Tailwind CSS 4, ESLint,
Playwright. Infrastructure: Docker Compose, Caddy 2, GitHub Actions, Oracle Cloud
(Ampere A1), Vercel.

## 7. Local setup

Full guide (Windows PowerShell and bash): [docs/local-development.md](docs/local-development.md).

```powershell
py -3.12 scripts\generate_env.py            # .env with random secrets (prints names only)
docker compose up --build -d                # postgres, redis, migrate, api, worker
Invoke-RestMethod http://localhost:8000/health/ready
cd frontend; Copy-Item .env.example .env.local; npm ci; npm run dev   # http://localhost:3000
```

`generate_env.py --merge` adds missing keys to an existing `.env` without touching
existing values. Without Docker: `uv sync`, `uv run alembic upgrade head`,
`uv run uvicorn app.main:app`, and `uv run celery -A app.workers.celery_app:celery_app
worker -B --pool=solo` (solo pool on Windows). Create an admin with
`docker compose exec api python -m app.cli create-admin --email admin@example.com`.

API usage with curl/PowerShell and the full manual checklist:
[docs/manual-testing.md](docs/manual-testing.md).

## 8. Production architecture

[docs/production-deployment.md](docs/production-deployment.md). One VM runs
`docker-compose.prod.yml`: Caddy (only service with published ports, 80/443,
automatic HTTPS, `/metrics` blocked), the API under gunicorn with 2 uvicorn workers,
a Celery worker (concurrency 2), a single beat, a one-shot migrate job, and PostgreSQL +
Redis on an internal-only network. Healthchecks, memory limits sized for 2 OCPU /
12 GB, rotated logs, demo rate limits, CORS restricted to the Vercel origin. Ops:
`scripts/setup_server.sh`, `deploy.sh`, `health_check.sh`, `backup_postgres.sh`,
`restore_postgres.sh`, `production_smoke_test.py`. CI/CD: `.github/workflows/ci.yml`
and `deploy.yml` (SSH deploy).

## 9. Oracle Cloud

[docs/oracle-cloud-deployment.md](docs/oracle-cloud-deployment.md): Ampere A1 Flex
(2 OCPU / 12 GB) in the home region, security list + host iptables for 80/443, a
hostname via your domain, sslip.io/nip.io or DuckDNS, optional OCI Object Storage via
the S3 compatibility API. Oracle Always Free resources are available for the life of
the account within the applicable Always Free limits; idle instances can be
reclaimed, and A1 capacity can be temporarily unavailable ("Out of host capacity").
The arm64 image was built and tested under emulation only.

## 10. Vercel

[docs/vercel-deployment.md](docs/vercel-deployment.md): Root Directory `frontend`,
`NEXT_PUBLIC_API_URL=https://<API_DOMAIN>` (public, not a secret), optionally
`NEXT_PUBLIC_SITE_URL` (canonical URL for Open Graph images) and the server-only
`DIP_CLIENT_IP_SECRET` (same value as the API's `CLIENT_IP_HEADER_SECRET`), then set `CORS_ALLOWED_ORIGINS` on the server to the Vercel URL. Sessions use
an HttpOnly cookie set by Next.js route handlers ([ADR-006](docs/adr/ADR-006-frontend-auth-bff.md)).

## 11. Environment variables

Production keys (`API_DOMAIN`, `CADDY_TLS`, `CORS_ALLOWED_ORIGINS`, storage, capacity,
rate limits, backups) are documented in [.env.production.example](.env.production.example)
and [docs/production-deployment.md](docs/production-deployment.md#environment). The
frontend reads `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL` and the server-only
`DIP_CLIENT_IP_SECRET` ([frontend/.env.example](frontend/.env.example)).
Backend (`.env`, [.env.example](.env.example)):

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
| `APP_NAME` / `APP_ENV` / `DEBUG` / `LOG_LEVEL` / `API_PORT` | `Document Intelligence & Analysis` / `development` / `false` / `INFO` / `8000` | `APP_ENV=production` enables stricter checks |
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
| `MIN_EVIDENCE_SIMILARITY` | `0.48` | if the best passage is below it, `/ask` answers "insufficient evidence" without calling the LLM |
| `ASK_TOP_K` / `ASK_CONTEXT_MIN_SIMILARITY` | `8` / `0.40` | passages sent to the LLM once the gate passed, and the floor for including them ([docs/rag.md](docs/rag.md)) |
| `ASK_SCOPED_MIN_SIMILARITY` | `0.20` | gate for questions scoped to one document or about a whole document ("summarize this document"); the LLM decides |
| `LLM_STRUCTURED_OUTPUT` | `true` | JSON-schema structured output; one automatic retry without it if the endpoint rejects the schema |
| `RERANKING_ENABLED` / `RERANKER_MODEL` / `RERANK_TOP_K` | `false` / `cross-encoder/ms-marco-MiniLM-L-6-v2` / `20` | optional cross-encoder |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` | `openai` / `gpt-4o-mini` / `https://api.openai.com/v1` | any OpenAI-compatible endpoint; `none` disables `/ask` |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_OUTPUT_TOKENS` / `LLM_TEMPERATURE` / `MAX_CONTEXT_TOKENS` | `30` / `900` / `0` / `4000` | |
| `API_DOCS_ENABLED` | empty (on; off in production) | `/docs`, `/redoc`, `/openapi.json` |
| `MAX_REQUEST_BODY_BYTES` / `UPLOAD_BODY_OVERHEAD_BYTES` | `1048576` / `65536` | enforced before the body is parsed |
| `SECURITY_HEADERS_ENABLED` | `true` | HSTS only in production |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_BACKEND` | `true` / `redis` | `memory` is per process, rejected in production |
| `RATE_LIMIT_REGISTER` / `_LOGIN` / `_LOGIN_PER_EMAIL` / `_UPLOAD` / `_SEARCH` / `_ASK` / `_REPROCESS` | `5/minute` / `10/minute` / `5/minute` / `10/minute` / `60/minute` / `10/minute` / `10/minute` | `N/second\|minute\|hour\|day` |
| `RATE_LIMIT_REGISTER_DAILY` / `_UPLOAD_DAILY` / `_UPLOAD_TOKEN` / `_ASK_DAILY` | `20/day` / `100/day` / `30/minute` / `200/day` | second, longer window for public demos |
| `RATE_LIMIT_DEMO` / `RATE_LIMIT_DEMO_GLOBAL` | `3/day` per IP / `200/day` total | demo sessions; fail closed if Redis is down |
| `DEMO_ENABLED` / `DEMO_MAX_QUESTIONS` / `DEMO_MAX_UPLOADS` / `DEMO_MAX_UPLOAD_BYTES` / `DEMO_ALLOWED_EXTENSIONS` / `DEMO_TTL_HOURS` / `DEMO_CLEANUP_INTERVAL_SECONDS` | `true` / `3` / `1` / `5242880` / `pdf` / `24` / `900` | [docs/demo-mode.md](docs/demo-mode.md) |
| `CLIENT_IP_HEADER_SECRET` | unset | >= 24 chars; the API trusts `X-DIP-Client-IP` from the BFF only with this shared secret (set the same value as `DIP_CLIENT_IP_SECRET` on Vercel). Strongly recommended in production, otherwise per-IP limits count Vercel's egress IPs |
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

S3 / OCI storage: `STORAGE_BACKEND=s3|oci` with `STORAGE_S3_BUCKET`,
`STORAGE_S3_ENDPOINT_URL`, `STORAGE_S3_REGION`, `STORAGE_S3_ACCESS_KEY_ID`,
`STORAGE_S3_SECRET_ACCESS_KEY`, `STORAGE_S3_PREFIX`.

## 12. Migrations

```bash
uv run alembic upgrade head
uv run alembic check          # "No new upgrade operations detected."
```

`0001` creates users, documents, jobs, audit logs and enables `vector`; `0002` adds
`document_chunks` (`vector(384)` + HNSW cosine index, generated `tsvector` + GIN) and
`document_processing_jobs.stage`. In production `deploy.sh` runs
`alembic upgrade head` in a one-off `migrate` container before the new API starts.
Never edit an applied revision.

## 13. Testing

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app tests scripts
export TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test   # pgvector/pgvector:pg16
uv run pytest --cov=app
cd frontend && npm run lint && npm run typecheck && npm run build
scripts/e2e_prod_local.sh          # production-like stack + Playwright (bash)
python3 scripts/production_smoke_test.py --base-url https://<API_DOMAIN> --register
```

Results (numbers in [FINAL_PROJECT_REPORT.md](FINAL_PROJECT_REPORT.md)):
backend 414 passed, 0 skipped, 96% coverage (real PostgreSQL + pgvector, Redis, S3-compatible server); ruff, format and mypy strict clean; frontend lint/typecheck/build clean; Playwright 10/10 against the production-like stack; production smoke test 13/13 checks. Not run: GitHub Actions, Windows, real OpenAI, real Oracle/Vercel.
Layers and commands: [docs/testing.md](docs/testing.md).

## 14. Security

[docs/security.md](docs/security.md): owner scoping in SQL (foreign ids -> 404),
Argon2id, JWT with pinned algorithm/issuer, HttpOnly session cookie + CSRF header and
origin check in the BFF, upload-only short-lived tokens, rate limits that fail closed
for credentials, body limits before parsing, prompt-injection containment and citation
validation, security headers and CSP, internal-only database/Redis/metrics, secrets
only from the environment (never logged), digest-pinned images, non-root containers.

## 15. Backup and recovery

[docs/backup-and-recovery.md](docs/backup-and-recovery.md):
`scripts/backup_postgres.sh [--with-files]` (verified `pg_dump -Fc`, checksum, optional
GPG and bucket copy, retention), `scripts/restore_postgres.sh --into <new db>` for
non-destructive checks, and `--replace-live-database --i-understand-this-overwrites-data`
(safety backup first) for real restores. A backup is taken before every deploy.

## 16. Known limitations

- Not deployed: no public URL; Oracle, Vercel, GitHub Actions and real OpenAI were not
  exercised. arm64 tested under QEMU emulation only.
- No OCR; scanned PDFs and images fail with an explicit message. DOCX extraction reads
  body paragraphs and tables only (no headers/footers, footnotes, comments, text boxes;
  no legacy `.doc`; no page numbers).
- Retrieval quality was measured on 18 synthetic queries over 6 short documents; the
  `/ask` evidence threshold (0.48) was calibrated on that set only. Citations show which
  passage the model pointed at; no entailment check.
- Fixed-window rate limits (bursts up to 2x at window edges); behind the Vercel BFF the
  per-IP limits count Vercel egress IPs unless `CLIENT_IP_HEADER_SECRET` /
  `DIP_CLIENT_IP_SECRET` are set. No refresh tokens, revocation or lockout;
  sessions end with the 30-minute token.
- Single VM: no replication, failover or horizontal scaling; backups are on the VM
  unless copied off. `/metrics` is unauthenticated (internal only).
- The document detail page shows metadata and processing state, not the document text
  (the API has no content-preview endpoint).
- `/ask` was fixed and replay-tested against hand-written reply fixtures and a local
  stub; it was **not** run against real OpenAI here. Run
  `python scripts/check_ask_real.py --base-url <api-url>` with your own key to verify.
- Impressum and Privacy pages are templates with highlighted placeholders; they are
  not legal advice and must be completed by the operator.
- The LLM client sends `max_tokens` and `temperature`; some reasoning models reject them.
- Performance measured on one machine with small documents; no load testing.

## 17. Future work

OCR for scanned PDFs; streaming `/ask` responses; refresh tokens and revocation;
a content-preview endpoint with highlighted chunks; per-tenant quotas; background
virus scanning; managed PostgreSQL or replication; OpenTelemetry tracing; retrieval
evaluation on real documents; image vulnerability scanning in CI; IaC (Terraform /
OCI Resource Manager) for the VM and network.
