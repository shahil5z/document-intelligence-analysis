<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/public/brand/logo-dark.png">
    <img src="frontend/public/brand/logo-light.png" alt="Document Intelligence &amp; Analysis" width="360">
  </picture>
</p>

<h1 align="center">Document Intelligence &amp; Analysis</h1>

<p align="center">
  Upload PDF, DOCX and TXT files, search them semantically, and ask questions that are
  answered only from your own documents, with numbered citations to the exact passages.
</p>

<p align="center">
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
  <img alt="PostgreSQL + pgvector" src="https://img.shields.io/badge/PostgreSQL_16-pgvector-4169E1?logo=postgresql&logoColor=white">
  <img alt="Next.js 16" src="https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

<p align="center">
  <strong>Live demo:</strong> coming soon (not deployed yet, see <a href="#project-status">status</a>)
</p>

---

## Overview

A multi-tenant document question-answering system (retrieval-augmented generation).
A background worker extracts, chunks and embeds uploaded text with a local model; users
search their own documents (semantic, keyword or hybrid) and ask questions that are
answered only from retrieved passages. Citations are validated against the passages
that were actually retrieved, and every query is scoped to the document owner inside SQL.

- **Backend**: FastAPI, PostgreSQL 16 + pgvector, Redis, Celery.
- **Frontend**: Next.js App Router in [`frontend/`](frontend), acting as a backend-for-frontend
  with an HttpOnly session cookie.
- **Production setup**: `docker-compose.prod.yml` + Caddy for a single Oracle Cloud
  Always Free Ampere VM, frontend on Vercel, ops scripts, CI/CD workflows.
- **Demo mode**: "Try the demo" creates an ephemeral account (1 PDF, 3 questions,
  deleted after 24 hours) that can be converted into a free account in place
  ([docs/demo-mode.md](docs/demo-mode.md)).
- **UI**: dark by default with a persisted light/dark toggle, sidebar on desktop and
  bottom navigation on mobile, chat-style Ask with clickable citation chips.

OCR is **not implemented**: scanned PDFs fail with an explicit message.

## Project status

Honest labels; the evidence is in the [verification report](docs/history/final-project-report.md).

| Area | Status |
| --- | --- |
| Backend API, processing pipeline, retrieval, `/ask` | **Working**, covered by unit, API and integration tests (real PostgreSQL + pgvector) |
| Frontend (all pages, demo mode, light/dark) | **Working**, lint/typecheck/build clean, Playwright suite |
| Production stack (Compose + Caddy + gunicorn) | **Verified locally** in a production-like run (Playwright 10/10, smoke test 13/13) |
| Backup / restore scripts | **Verified locally** (round trip and restore drill) |
| arm64 image | **Verified under QEMU emulation only** |
| Live deployment (Oracle VM + Vercel) | **Configured, not deployed**: [deployment checklist](docs/deployment-checklist.md) |
| GitHub Actions CI/CD | **Written, not yet run on GitHub** (commands verified locally) |
| `/ask` against real OpenAI | **Not verified**: tested with replayed fixtures and a local stub LLM |
| OCR, streaming answers, refresh tokens | **Not implemented** (see [future work](#future-work)) |

## Screenshots

Captured with Playwright against the local production-like stack (`/ask` answered by
the local **stub** LLM, not OpenAI).

| Dark (default) | Light |
| --- | --- |
| ![Landing page, dark](docs/screenshots/landing-desktop-dark.png) | ![Landing page, light](docs/screenshots/landing-desktop-light.png) |
| ![Ask with citations, dark](docs/screenshots/ask-citations-dark.png) | ![Ask with citations, light](docs/screenshots/ask-citations-light.png) |
| ![Dashboard, dark](docs/screenshots/dashboard-desktop-dark.png) | ![Dashboard, light](docs/screenshots/dashboard-desktop-light.png) |
| ![Demo upload, dark](docs/screenshots/demo-upload-ready-dark.png) | ![Demo limit dialog, light](docs/screenshots/demo-limit-modal-light.png) |
| ![Hybrid search, dark](docs/screenshots/search-desktop-dark.png) | ![Architecture page, dark](docs/screenshots/architecture-desktop-dark.png) |
| ![Ask on mobile, dark](docs/screenshots/ask-mobile-dark.png) | ![Ask on mobile, light](docs/screenshots/ask-mobile-light.png) |

## Architecture

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

## Quick start

Requirements: Docker with Compose, Python 3.12 (only for the env generator), Node.js 20.9+.

```bash
git clone https://github.com/shahil5z/document-intelligence-platform.git
cd document-intelligence-platform
python3 scripts/generate_env.py              # writes .env with random secrets (prints names only)
docker compose up --build -d                 # postgres, redis, migrate, api, worker
curl http://localhost:8000/health/ready      # API docs: http://localhost:8000/docs

cd frontend && cp .env.example .env.local && npm ci && npm run dev   # http://localhost:3000
```

Search and upload work out of the box; `/ask` additionally needs `OPENAI_API_KEY` (any
OpenAI-compatible endpoint via `LLM_BASE_URL`) or the bundled stub
(`docker-compose.stub-llm.yml`). Windows PowerShell commands, running without Docker and
creating an admin: [docs/local-development.md](docs/local-development.md). API usage and
the manual checklist: [docs/manual-testing.md](docs/manual-testing.md).

## Features

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

## Tech stack

Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (sync, psycopg 3), Alembic,
PostgreSQL 16 + pgvector (HNSW) + full-text search, Redis 7, Celery 5, PyJWT, pwdlib
(Argon2id), pypdf, python-docx, sentence-transformers (CPU torch), boto3, httpx2,
gunicorn + uvicorn-worker, uv, pytest, ruff, mypy (strict).
Frontend: Next.js 16 (App Router), React, TypeScript, Tailwind CSS 4, ESLint,
Playwright. Infrastructure: Docker Compose, Caddy 2, GitHub Actions, Oracle Cloud
(Ampere A1), Vercel.

## Configuration

Only three values are **mandatory**; everything else has a safe default.
`scripts/generate_env.py` creates all three (`--merge` adds missing keys to an existing
`.env` without touching existing values).

| Mandatory | Why |
| --- | --- |
| `JWT_SECRET_KEY` | >= 32 characters; placeholders are rejected |
| `POSTGRES_PASSWORD` | unless `DATABASE_URL` is set (not required when `APP_ENV=test`) |
| `REDIS_PASSWORD` | unless `REDIS_URL` is set (not required when `APP_ENV=test`) |

`OPENAI_API_KEY` is needed only for `/ask`. Every variable with its default:
[docs/configuration.md](docs/configuration.md), [.env.example](.env.example),
[.env.production.example](.env.production.example) and
[frontend/.env.example](frontend/.env.example).

## Migrations

```bash
uv run alembic upgrade head
uv run alembic check          # "No new upgrade operations detected."
```

`0001` creates users, documents, jobs, audit logs and enables `vector`; `0002` adds
`document_chunks` (`vector(384)` + HNSW cosine index, generated `tsvector` + GIN) and
`document_processing_jobs.stage`. In production `deploy.sh` runs
`alembic upgrade head` in a one-off `migrate` container before the new API starts.
Never edit an applied revision.

## Testing

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app tests scripts
export TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test   # pgvector/pgvector:pg16
uv run pytest --cov=app
cd frontend && npm run lint && npm run typecheck && npm run build
scripts/e2e_prod_local.sh          # production-like stack + Playwright (bash)
python3 scripts/production_smoke_test.py --base-url https://<API_DOMAIN> --register
```

Latest local run: ruff, format and mypy (strict) clean; **488 passed, 14 skipped, 96%
coverage** against real PostgreSQL + pgvector (the skipped tests need an S3-compatible
server or an authenticated Redis, set via `TEST_S3_*` / `TEST_REDIS_URL`); frontend
lint, typecheck and build clean; Playwright theme suite 5/5 against `next start`. The
full Playwright flow (10/10) and the production smoke test (13/13) were run against
the production-like stack ([report](docs/history/final-project-report.md)). Not run:
GitHub Actions, Windows, real OpenAI, real Oracle/Vercel.
Layers and commands: [docs/testing.md](docs/testing.md).

## Production architecture

[docs/production-deployment.md](docs/production-deployment.md). One VM runs
`docker-compose.prod.yml`: Caddy (only service with published ports, 80/443,
automatic HTTPS, `/metrics` blocked), the API under gunicorn with 2 uvicorn workers,
a Celery worker (concurrency 2), a single beat, a one-shot migrate job, and PostgreSQL +
Redis on an internal-only network. Healthchecks, memory limits sized for 2 OCPU /
12 GB, rotated logs, demo rate limits, CORS restricted to the Vercel origin. Ops:
`scripts/setup_server.sh`, `deploy.sh`, `health_check.sh`, `backup_postgres.sh`,
`restore_postgres.sh`, `production_smoke_test.py`. CI/CD: `.github/workflows/ci.yml`
and `deploy.yml` (SSH deploy).

## Oracle Cloud

[docs/oracle-cloud-deployment.md](docs/oracle-cloud-deployment.md): Ampere A1 Flex
(2 OCPU / 12 GB) in the home region, security list + host iptables for 80/443, a
hostname via your domain, sslip.io/nip.io or DuckDNS, optional OCI Object Storage via
the S3 compatibility API. Oracle Always Free resources are available for the life of
the account within the applicable Always Free limits; idle instances can be
reclaimed, and A1 capacity can be temporarily unavailable ("Out of host capacity").
The arm64 image was built and tested under emulation only.

## Vercel

[docs/vercel-deployment.md](docs/vercel-deployment.md): Root Directory `frontend`,
`NEXT_PUBLIC_API_URL=https://<API_DOMAIN>` (public, not a secret), optionally
`NEXT_PUBLIC_SITE_URL` (canonical URL for Open Graph images) and the server-only
`DIP_CLIENT_IP_SECRET` (same value as the API's `CLIENT_IP_HEADER_SECRET`), then set `CORS_ALLOWED_ORIGINS` on the server to the Vercel URL. Sessions use
an HttpOnly cookie set by Next.js route handlers ([ADR-006](docs/adr/ADR-006-frontend-auth-bff.md)).

## Security

[docs/security.md](docs/security.md): owner scoping in SQL (foreign ids -> 404),
Argon2id, JWT with pinned algorithm/issuer, HttpOnly session cookie + CSRF header and
origin check in the BFF, upload-only short-lived tokens, rate limits that fail closed
for credentials, body limits before parsing, prompt-injection containment and citation
validation, security headers and CSP, internal-only database/Redis/metrics, secrets
only from the environment (never logged), digest-pinned images, non-root containers.

## Backup and recovery

[docs/backup-and-recovery.md](docs/backup-and-recovery.md):
`scripts/backup_postgres.sh [--with-files]` (verified `pg_dump -Fc`, checksum, optional
GPG and bucket copy, retention), `scripts/restore_postgres.sh --into <new db>` for
non-destructive checks, and `--replace-live-database --i-understand-this-overwrites-data`
(safety backup first) for real restores. A backup is taken before every deploy.

## Known limitations

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

## Future work

OCR for scanned PDFs; streaming `/ask` responses; refresh tokens and revocation;
a content-preview endpoint with highlighted chunks; per-tenant quotas; background
virus scanning; managed PostgreSQL or replication; OpenTelemetry tracing; retrieval
evaluation on real documents; image vulnerability scanning in CI; IaC (Terraform /
OCI Resource Manager) for the VM and network.

## Documentation

| Topic | Document |
| --- | --- |
| Architecture and decisions | [docs/architecture.md](docs/architecture.md), [docs/adr/](docs/adr) |
| Processing, retrieval, RAG | [docs/document-processing.md](docs/document-processing.md), [docs/retrieval.md](docs/retrieval.md), [docs/rag.md](docs/rag.md) |
| Local development and testing | [docs/local-development.md](docs/local-development.md), [docs/testing.md](docs/testing.md), [docs/manual-testing.md](docs/manual-testing.md) |
| Deployment | [docs/production-deployment.md](docs/production-deployment.md), [docs/oracle-cloud-deployment.md](docs/oracle-cloud-deployment.md), [docs/vercel-deployment.md](docs/vercel-deployment.md), [docs/deployment-checklist.md](docs/deployment-checklist.md) |
| Operations | [docs/backup-and-recovery.md](docs/backup-and-recovery.md), [docs/observability.md](docs/observability.md), [docs/performance.md](docs/performance.md) |
| Security | [docs/security.md](docs/security.md) |
| Portfolio notes and history | [docs/portfolio.md](docs/portfolio.md), [docs/history/](docs/history) (stage handoffs and the final verification report) |

## License

[MIT](LICENSE) © 2026 Shohrab Haque Shahil.

Repository, package, Docker service and database names keep the original
`document-intelligence-platform` / `dip` slugs; only user-facing text uses the
product name.
