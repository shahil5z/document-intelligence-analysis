# Document Intelligence Platform

Backend for ingesting documents and turning them into searchable, citable knowledge.
This repository currently contains the **foundation stage (DIP1)**: authenticated
multi-user uploads, durable storage, an asynchronous processing pipeline with explicit
job states, audit logging, and the operational basics (structured logs, request ids,
health probes, Docker Compose). Retrieval features are planned and listed in the roadmap.

## Why

Question answering over private documents is only as trustworthy as the system
underneath it: who uploaded what, whether a file was processed, why a job failed, and
whether one user can ever see another user's data. DIP1 builds that layer first, with
tests against a real PostgreSQL database, so retrieval and generation can be added on
top without reworking ownership, job tracking or storage.

## Architecture overview

```mermaid
flowchart LR
    client[Client] --> api[FastAPI API]
    api --> pg[(PostgreSQL + pgvector ext.)]
    api --> redis[(Redis broker)]
    api --> storage[[File storage]]
    worker[Celery worker] --> redis
    worker --> pg
    worker --> storage
```

Routes -> services (transaction boundaries) -> repositories (owner-scoped queries) ->
SQLAlchemy models. Uploads create a processing job that a Celery worker executes; job
and document status follow an explicit state machine. Details, sequence diagrams and
the ER diagram are in [ARCHITECTURE.md](ARCHITECTURE.md); decisions are in
[docs/adr/](docs/adr).

## Stack

Python 3.12 · FastAPI · Pydantic v2 / pydantic-settings · SQLAlchemy 2.x (sync, psycopg 3)
· Alembic · PostgreSQL 16 (`pgvector/pgvector:pg16`) · Redis 7 · Celery 5 · PyJWT ·
pwdlib (Argon2id) · uv · pytest · ruff · mypy (strict) · Docker / Docker Compose.

## Current capabilities

| Area | Status |
| --- | --- |
| Register / login (JSON and OAuth2 form) / `GET /auth/me`, JWT access tokens | Implemented, tested |
| Roles `user` / `admin`, admin-only user and audit-log listing | Implemented, tested |
| Upload PDF/DOCX/TXT with allow-list, magic-byte check, streamed size limit, SHA-256, per-user duplicate detection (409) | Implemented, tested |
| List (paginated), detail, status, delete - strictly per owner (404 for others) | Implemented, tested |
| Celery job per upload: claim, integrity check (size + SHA-256), complete/fail, retries for transient errors | Implemented, tested (processor) and run end to end with a real worker |
| Audit log for register, login, failed login, upload, delete | Implemented, tested |
| JSON logs, `X-Request-ID`, consistent error envelope, liveness/readiness | Implemented, tested |
| Text extraction, OCR, chunking, embeddings, vector search, hybrid retrieval, RAG `/ask` with citations | **Planned for DIP2** - not implemented |
| CI/CD, rate limiting, metrics/tracing, container hardening | **Planned for DIP3** - not implemented |

A document that reaches `completed` today has been stored and integrity-verified by
the worker; no content has been extracted from it yet.

## Project structure

```
app/
  main.py                  application factory, middleware, routers
  cli.py                   python -m app.cli create-admin
  api/routes/              auth, documents, audit_logs, admin, health
  api/dependencies/        db session, auth guards, pagination, service wiring
  core/                    config, security, logging, request_context, middleware, errors
  db/                      base, session, models/, repositories/
  domain/                  enums, state_machine
  schemas/                 Pydantic request/response models
  services/                auth, documents, audit, users, health, upload validation
  storage/                 StorageService interface, LocalStorage, factory
  workers/                 celery_app, tasks, dispatcher, processing, pipeline
alembic/                   env.py and versions/ (initial schema)
tests/                     unit/, api/, integration/ (real PostgreSQL)
scripts/smoke_test.py      end-to-end check against a running stack
docs/adr/                  architecture decision records
```

## Local setup

Requirements: Docker with Compose v2 **or** Python 3.12 + [uv](https://docs.astral.sh/uv/),
PostgreSQL 16 with pgvector, and Redis.

```bash
cp .env.example .env
# set JWT_SECRET in .env:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Option A: Docker Compose (everything)

```bash
docker compose up --build -d
docker compose ps                       # postgres, redis healthy; migrate exited 0; api, worker up
curl http://localhost:8000/health/ready
python scripts/smoke_test.py            # optional end-to-end check
```

Services: `postgres`, `redis`, `migrate` (runs `alembic upgrade head` once), `api`
(port 8000), `worker`. API and worker share the `storage_data` volume.

### Option B: run the Python processes on the host

```bash
uv sync                                 # creates .venv with app + dev dependencies
# point DATABASE_URL / REDIS_URL / CELERY_* in .env at your PostgreSQL and Redis
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --no-access-log
uv run celery -A app.workers.celery_app:celery_app worker --loglevel=INFO   # second terminal
```

On Windows, start the worker with `--pool=solo` (Celery's default prefork pool is not
supported there).

Create an administrator (password from `ADMIN_PASSWORD` or a prompt):

```bash
uv run python -m app.cli create-admin --email admin@example.com
docker compose exec api python -m app.cli create-admin --email admin@example.com
```

## Environment variables

| Variable | Default | Notes |
| --- | --- | --- |
| `JWT_SECRET` | *(required)* | >= 32 characters; placeholder-looking values rejected when `ENVIRONMENT=production` |
| `JWT_ALGORITHM` | `HS256` | HS256/HS384/HS512 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | 1-1440 |
| `DATABASE_URL` | `postgresql+psycopg://dip:dip@localhost:5432/dip` | psycopg 3 driver |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `10` | per process |
| `REDIS_URL` | `redis://localhost:6379/0` | readiness check |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` / `/1` | task results are not stored (state lives in PostgreSQL) |
| `CELERY_TASK_MAX_RETRIES` / `CELERY_RETRY_BACKOFF_SECONDS` | `3` / `10` | exponential backoff |
| `MAX_UPLOAD_SIZE_BYTES` | `10485760` | 413 above this |
| `STORAGE_PATH` | `./storage_data` | `/data/storage` in containers |
| `ALLOWED_EXTENSIONS` | `pdf,docx,txt` | comma separated |
| `ALLOWED_CONTENT_TYPES` | PDF, DOCX, `text/plain` | comma separated |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | `*` rejected |
| `ENVIRONMENT` | `development` | `development` / `test` / `production` |
| `LOG_LEVEL` | `INFO` | |
| `TEST_DATABASE_URL` | - | tests only; database name must contain `test` |

## Migrations

```bash
uv run alembic upgrade head
uv run alembic check                    # must report "No new upgrade operations detected."
uv run alembic revision -m "describe change"   # then edit the generated file by hand
```

The initial revision (`0001`) creates the four tables and ENUM types and enables the
`vector` extension. Never edit an applied revision; add a new one.

## Running the API and worker

- API: `uv run uvicorn app.main:app` (container: `uvicorn ... --proxy-headers --no-access-log`;
  request logging is done by the app's middleware with request ids).
- Worker: `uv run celery -A app.workers.celery_app:celery_app worker --loglevel=INFO`.

## Tests and quality checks

Tests need a disposable PostgreSQL database (the suite runs the Alembic migrations and
truncates tables after each test). Celery is replaced by a recording fake, so Redis is
not required; one readiness test additionally runs when `TEST_REDIS_URL` is set.

```bash
docker run -d --name dip-test-db -e POSTGRES_USER=dip -e POSTGRES_PASSWORD=dip \
  -e POSTGRES_DB=dip_test -p 5433:5432 pgvector/pgvector:pg16
export TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test
uv run pytest --cov=app
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Last recorded run (DIP1, on the development box): 99 passed (with `TEST_REDIS_URL` set),
94 % line coverage of `app/`; ruff check, ruff format --check and mypy --strict clean.
See [DIP3_HANDOFF.md](DIP3_HANDOFF.md) for the inventory.

## API documentation

With the API running: Swagger UI at `/docs` (use **Authorize** with email as username),
ReDoc at `/redoc`, schema at `/openapi.json`.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | - | liveness |
| GET | `/health/ready` | - | PostgreSQL + Redis readiness (503 if down) |
| POST | `/auth/register` | - | create user (role `user`) |
| POST | `/auth/login` | - | JSON login -> JWT |
| POST | `/auth/token` | - | OAuth2 form login -> JWT (Swagger) |
| GET | `/auth/me` | user | current user |
| POST | `/documents` | user | multipart upload, queues processing |
| GET | `/documents` | user | `page`, `page_size` (max 100) |
| GET | `/documents/{id}` | user | metadata |
| GET | `/documents/{id}/status` | user | status + latest job |
| DELETE | `/documents/{id}` | user | delete record, jobs and file (204) |
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
- No secrets in the repository (`.env` is git-ignored); log redaction for sensitive keys.
- CORS restricted to configured origins; containers run as a non-root user.

Known gaps are listed below and in [DIP3_HANDOFF.md](DIP3_HANDOFF.md).

## Roadmap

- **DIP2** - text extraction (PDF, DOCX, TXT; OCR for scanned PDFs), chunking,
  embeddings stored with pgvector, semantic and hybrid (keyword + vector) search,
  `/ask` endpoint with answers grounded in cited chunks. See [DIP2_HANDOFF.md](DIP2_HANDOFF.md).
- **DIP3** - full CI/CD with GitHub Actions, rate limiting, metrics and tracing,
  container security scanning, hardening and final documentation. See [DIP3_HANDOFF.md](DIP3_HANDOFF.md).

## Known limitations

- No content processing yet: `completed` means stored and integrity-verified.
- The multipart body is fully received (spooled by Starlette) before the size limit is
  applied while copying to storage; there is no request-size limit in front of parsing.
- DOCX validation only checks the ZIP signature.
- If the broker is down at upload time the document is marked `failed`; there is no
  re-process endpoint yet, and the duplicate check means the user must delete and re-upload.
- No rate limiting, account lockout, refresh tokens or token revocation.
- Local filesystem storage only; API and worker must share the volume.
- Performance and scalability are not measured yet.
