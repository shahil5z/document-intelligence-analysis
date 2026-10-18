# Document Intelligence Platform

Backend for ingesting documents and turning them into searchable, citable knowledge.
The project is built in three stages:

| Stage | Scope | Status |
| --- | --- | --- |
| **DIP1** | Foundation: auth, uploads, storage, async job pipeline, audit log, ops basics, Docker | **Implemented** (this repository) |
| **DIP2** | Text extraction/OCR, chunking, embeddings (pgvector), semantic + hybrid search, `/ask` with citations | Planned - only extension points exist |
| **DIP3** | CI/CD, rate limiting, metrics/tracing, container hardening, final docs | Planned |

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
    api --> redis[(Redis broker, password)]
    api --> storage[[File storage]]
    worker[Celery worker] --> redis
    worker --> pg
    worker --> storage
```

Routes -> services (transaction boundaries) -> repositories (owner-scoped queries) ->
SQLAlchemy models. Uploads create a processing job that a Celery worker executes; job
and document status follow an explicit state machine. Diagrams (system, upload flow,
job flow, ER) are in [docs/architecture.md](docs/architecture.md), decisions in
[docs/adr/](docs/adr), the full stage hand-off in [DIP1_HANDOFF.md](DIP1_HANDOFF.md).

## Stack

Python 3.12 · FastAPI · Pydantic v2 / pydantic-settings · SQLAlchemy 2.x (sync, psycopg 3)
· Alembic · PostgreSQL 16 (`pgvector/pgvector:pg16`) · Redis 7 · Celery 5 · PyJWT ·
pwdlib (Argon2id) · OpenAI SDK (provider factory only, DIP2) · uv · pytest · ruff ·
mypy (strict) · Docker / Docker Compose.

## Current capabilities (DIP1)

| Area | Status |
| --- | --- |
| Register / login (JSON and OAuth2 form) / `GET /auth/me`, JWT access tokens | Implemented, tested |
| Roles `user` / `admin`, admin-only user and audit-log listing | Implemented, tested |
| Upload PDF/DOCX/TXT with allow-list, magic-byte check, streamed size limit, SHA-256, per-user duplicate detection (409) | Implemented, tested |
| List (paginated), detail, status, delete - strictly per owner (404 for others) | Implemented, tested |
| Celery job per upload: claim, integrity check (size + SHA-256), complete/fail, retries for transient errors | Implemented, tested; run end to end with a real worker |
| Audit log for register, login, failed login, upload, delete | Implemented, tested |
| JSON logs, `X-Request-ID`, consistent error envelope, `/health`, `/health/live`, `/health/ready` | Implemented, tested |
| Password-protected Redis; secrets validated at startup, never logged | Implemented, tested |
| `LLMProvider` / `EmbeddingProvider` interfaces + OpenAI factory | Implemented and unit-tested with a fake client; **no OpenAI call is made anywhere in DIP1** |
| Extraction, OCR, chunking, embeddings, vector search, hybrid retrieval, RAG `/ask` with citations | **Planned for DIP2** - not implemented |

A document that reaches `completed` today has been stored and integrity-verified by
the worker; no content has been extracted from it yet.

## Project structure

```
app/
  main.py                  application factory, middleware, routers
  cli.py                   python -m app.cli create-admin
  ai/                      provider protocols + OpenAI factory (DIP2 extension point)
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
scripts/generate_env.py    creates .env with random secrets
scripts/smoke_test.py      end-to-end check against a running stack
docs/                      architecture.md, portfolio.md, adr/
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
The key file may contain `OPENAI_API_KEY=...` or just the key. `OPENAI_API_KEY` is
optional in DIP1. `.env` and a root-level file named `env` are git-ignored.

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
`storage_data` volume. Postgres and Redis are not published to the host.

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
- These Windows notes were not executed during DIP1 (development and verification ran on Linux).

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
| `OPENAI_API_KEY` | unset | optional; only read by `app/ai/factory.py` (DIP2) |
| `TEST_DATABASE_URL` / `TEST_REDIS_URL` | - | tests only (commented out in `.env.example`) |

Further tunables with safe defaults (not in `.env.example`): `DB_POOL_SIZE`,
`DB_MAX_OVERFLOW`, `CELERY_TASK_MAX_RETRIES`, `CELERY_RETRY_BACKOFF_SECONDS`,
`UPLOAD_CHUNK_SIZE_BYTES`, `JWT_ISSUER`, `OPENAI_CHAT_MODEL`, `OPENAI_EMBEDDING_MODEL`,
`OPENAI_TIMEOUT_SECONDS`.

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
extension. Never edit an applied revision; add a new one.

## Tests and quality checks

Tests need a disposable PostgreSQL database (the suite runs the Alembic migrations and
truncates tables after each test). Celery is replaced by a recording fake and OpenAI by
a fake client, so neither Redis nor network access is required. Two readiness tests
additionally run when `TEST_REDIS_URL` points at a Redis (one needs a password in it).

```bash
docker run -d --name dip-test-db -e POSTGRES_USER=dip -e POSTGRES_PASSWORD=dip \
  -e POSTGRES_DB=dip_test -p 5433:5432 pgvector/pgvector:pg16
export TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test
export TEST_REDIS_URL='redis://:<redis-password>@localhost:6380/0'   # optional
uv run pytest --cov=app
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Last recorded run: see [DIP1_HANDOFF.md](DIP1_HANDOFF.md#12-tests-executed-and-real-results).

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
- Secrets only from the environment, as `SecretStr`; startup fails on missing or
  placeholder secrets; `.env`/`env` git-ignored; log redaction of sensitive keys.
- Redis requires a password; Postgres/Redis are not exposed by compose.
- CORS restricted to configured origins; containers run as a non-root user.

## Roadmap

- **DIP2** - extraction (PDF, DOCX, TXT; OCR for scans), chunking, embeddings with
  pgvector, semantic + hybrid search, `/ask` with cited answers. Where each piece goes:
  [DIP1_HANDOFF.md](DIP1_HANDOFF.md#17-extension-points-for-dip2).
- **DIP3** - GitHub Actions CI/CD, rate limiting, metrics and tracing, container
  scanning and hardening, final docs: [DIP3_HANDOFF.md](DIP3_HANDOFF.md).

## Known limitations

- No content processing yet: `completed` means stored and integrity-verified.
- The multipart body is fully received (spooled by Starlette) before the size limit is
  applied while copying to storage; there is no request-size limit in front of parsing.
- DOCX validation only checks the ZIP signature.
- If the broker is down at upload time the document is marked `failed`; there is no
  re-process endpoint yet, and the duplicate check means the user must delete and re-upload.
- No rate limiting, account lockout, refresh tokens or token revocation.
- The Redis password is passed to `redis-server` as a command-line argument (visible to
  anyone who can run `docker inspect` on the host).
- Local filesystem storage only; API and worker must share the volume.
- Performance and scalability are not measured yet.
