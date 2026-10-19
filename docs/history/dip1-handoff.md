# DIP1 hand-off: backend foundation

> **Historical stage record.** The numbers and NOT VERIFIED items below describe the
> state at the end of this stage and are kept unchanged as history. The current,
> verified state of the whole system (tests, Docker, CI, security, benchmark) is in
> [verification report](final-project-report.md); where this file disagrees with
> it, the final report and the code win.
>
> Superseded since DIP1: Redis no longer receives `--requirepass` on the command line
> (0600 config file); rate limits, metrics and hardening were added in DIP3; the
> stale-job reconciler and terminal failure on retry exhaustion were added in the
> final phase; the "DIP2" plan section is implemented (see dip2-handoff.md).

This is the single hand-off document for DIP1 and the starting point for DIP2
(it replaces the former `dip2-handoff.md`). DIP3 specifics are in
[dip3-handoff.md](dip3-handoff.md). Everything listed as implemented was executed;
anything not executed is marked as such.

## 1. What was implemented

- FastAPI application with JWT auth (register, JSON login, OAuth2 form login, `/auth/me`),
  roles `user`/`admin`, admin-only listings, and a per-user audit trail.
- Document upload (PDF, DOCX, TXT) with extension + content-type allow-list, magic-byte
  check, streamed size limit (413), SHA-256, per-user duplicate detection (409), owner-scoped
  list/detail/status/delete (404 for other users' documents).
- Asynchronous processing: one job per upload executed by a Celery worker with an explicit
  state machine, idempotent re-delivery handling, retries for transient errors and safe
  error messages. The only processing step today is an integrity check (size + SHA-256).
- Storage abstraction with a local backend and path-traversal guard; `STORAGE_BACKEND`
  selects the backend and unknown values stop the API and worker at startup.
- Configuration from environment only: secrets as `SecretStr`, required-secret and
  placeholder checks, URLs derived from `POSTGRES_*` / `REDIS_*` with overrides.
- Password-protected Redis in compose; broker, worker and readiness use the authenticated URL.
- Optional `OPENAI_API_KEY` and `app/ai/` provider interfaces with an OpenAI-backed factory
  (no calls are made in DIP1).
- `scripts/generate_env.py` (random secrets) and `scripts/smoke_test.py` (end-to-end check).
- JSON logging, request ids, uniform error envelope, `/health`, `/health/live`, `/health/ready`.
- Docker multi-stage image (non-root), compose stack with healthchecks and a migrate service.

Not implemented (DIP2): extraction, OCR, chunking, embeddings, vector tables, search,
hybrid retrieval, `/ask`, citations. Not implemented (DIP3): CI/CD, rate limiting,
metrics/tracing, image scanning.

## 2. Final architecture

```
client -> FastAPI (routes -> services -> repositories -> SQLAlchemy) -> PostgreSQL 16 (+pgvector ext.)
                  \-> LocalStorage (shared volume)
                  \-> Redis (AUTH) -> Celery worker -> DocumentProcessor -> pipeline steps
```

Sync SQLAlchemy and `def` routes (threadpool) everywhere, shared by API, worker and CLI
(ADR-005). Services own transactions and commit explicitly; repositories never commit.
Diagrams: [docs/architecture.md](../architecture.md). Decisions: [docs/adr/](../adr).

## 3. Directory structure

```
app/
  main.py, cli.py
  ai/            base.py (protocols), openai_provider.py, factory.py, errors.py
  api/           router.py, responses.py, routes/{auth,documents,audit_logs,admin,health}.py,
                 dependencies/{db,auth,settings,pagination,services}.py
  core/          config.py, security.py, logging.py, request_context.py, middleware.py, errors.py
  db/            base.py, session.py, models/{user,document,processing_job,audit_log,mixins,enum_types}.py,
                 repositories/{users,documents,jobs,audit_logs}.py
  domain/        enums.py, state_machine.py
  schemas/       auth, user, document, audit_log, health, common
  services/      auth_service, document_service, audit_service, user_service, health_service,
                 upload_validation, task_dispatcher
  storage/       base.py, local.py, factory.py
  workers/       celery_app.py, tasks.py, dispatcher.py, processing.py, pipeline.py
alembic/         env.py, versions/20261017_0001_initial_schema.py
scripts/         generate_env.py, smoke_test.py
tests/           unit/, api/, integration/, conftest.py, factories.py
docs/            architecture.md, portfolio.md, adr/ADR-001..005
```

## 4. Database schema

Revision `0001` (hand-written, `alembic check` reports no diff). Native ENUMs:
`user_role(user, admin)`, `document_status(uploaded, queued, processing, completed, failed)`,
`job_status(pending, queued, processing, retrying, completed, failed)`. Extension `vector`
enabled, no vector columns.

| Table | Columns | Constraints / indexes |
| --- | --- | --- |
| `users` | id UUID, email, password_hash, role, is_active, created_at, updated_at | unique index on email |
| `documents` | id, owner_id, filename (generated), original_filename (sanitised), content_type, file_size, storage_key, status, checksum_sha256, timestamps | FK owner_id -> users ON DELETE CASCADE; unique (owner_id, checksum_sha256); unique storage_key; indexes owner_id, status, (owner_id, created_at) |
| `document_processing_jobs` | id, document_id, status, task_id, error_message, attempts, started_at, completed_at, timestamps | FK document_id ON DELETE CASCADE; indexes document_id, status, task_id |
| `audit_logs` | id, user_id, action, resource_type, resource_id, metadata JSONB (ORM attr `details`), created_at | FK user_id ON DELETE SET NULL; indexes user_id, action, created_at |

## 5. Endpoints

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/health`, `/health/live`, `/health/ready` | - |
| POST | `/auth/register`, `/auth/login`, `/auth/token` | - |
| GET | `/auth/me` | user |
| POST / GET | `/documents` | user |
| GET / DELETE | `/documents/{id}` | user |
| GET | `/documents/{id}/status` | user |
| GET | `/audit-logs/me` | user |
| GET | `/admin/users`, `/admin/audit-logs` | admin |

OpenAPI at `/docs`, `/redoc`, `/openapi.json` (all returned 200 in the compose run).

## 6. Auth design

- Argon2id via pwdlib; unknown emails run a dummy verification; identical error for
  unknown email / wrong password; failed logins are audited.
- HS256 JWT (`JWT_SECRET_KEY`), claims `sub`, `role`, `type=access`, `jti`, `iss`, `iat`, `exp`;
  decode checks signature, expiry, issuer, required claims and type.
- `get_current_user` reloads the user from the database (role/active flag are not trusted
  from the token); `get_current_active_user` -> 403 if disabled; `require_admin` -> 403.
- Registration always creates role `user`; admins via `python -m app.cli create-admin`.

## 7. Document lifecycle

Document: `uploaded -> queued -> processing -> completed | failed`; transient retry
`processing -> queued`; `completed|failed -> queued` reserved for reprocessing.
Job: `pending -> queued -> processing -> completed | failed | retrying`; `retrying ->
processing | failed`. Transitions only through `app/domain/state_machine.py`.

Upload order: validate -> stream to storage (hash, size, magic bytes) -> duplicate check ->
insert document + job, set both `queued`, audit, **commit** -> publish task with the
pre-generated `task_id`. Broker failure -> job and document `failed` with a safe message.
Delete: audit + delete row (jobs cascade) -> commit -> delete file (failure logged, orphan file).

## 8. Redis / Celery design

- Redis runs with `--requirepass`; `REDIS_PASSWORD` is required outside `APP_ENV=test`.
  URL `redis://:<password>@host:port/db` is built with the password percent-encoded.
- Celery broker and result backend default to that URL (`CELERY_*` overrides). Task
  `documents.process` is `ignore_result=True`; job state lives in PostgreSQL.
- `task_acks_late`, `task_reject_on_worker_lost`, prefetch 1, soft/hard time limits
  240/300 s, broker socket timeouts so publishing fails within seconds if Redis is down.
- `DocumentProcessor` (`app/workers/processing.py`): row-locks the job, skips missing or
  terminal jobs, re-claims a job left in `processing`, runs pipeline steps, records
  `completed` / `failed` (safe message) / `retrying` (exponential backoff, then failure).
- The upload's request id is passed to the task and appears in worker logs.

## 9. Storage design

`StorageService` (`save(key, chunks)`, `iter_chunks`, `delete`, `exists`); `LocalStorage`
writes to a temp file, fsyncs, renames atomically; keys must match a strict grammar and
resolve inside the root (blocks `..`, absolute paths, symlink escapes). Keys:
`documents/<owner_id>/<document_uuid_hex>.<ext>`; never exposed by the API.
`STORAGE_BACKEND=local` is the only supported value.

## 10. Environment variables

From `.env.example`: `APP_NAME`, `APP_ENV`, `DEBUG`, `LOG_LEVEL`, `API_PORT`,
`JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_HOST`,
`REDIS_PORT`, `REDIS_DB`, `REDIS_PASSWORD`, `STORAGE_BACKEND`, `STORAGE_PATH`,
`MAX_UPLOAD_SIZE_BYTES`, `ALLOWED_EXTENSIONS`, `ALLOWED_CONTENT_TYPES`,
`CORS_ALLOWED_ORIGINS`, `OPENAI_API_KEY`; commented optional overrides `DATABASE_URL`,
`REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `TEST_DATABASE_URL`,
`TEST_REDIS_URL`. Defaults and rules: [README.md](../configuration.md).

## 11. Commands

```bash
python scripts/generate_env.py [--openai-key-file env | --openai-key-env VAR] [--force]
docker compose up --build -d && uv run python scripts/smoke_test.py
uv sync && uv run alembic upgrade head && uv run alembic check
uv run uvicorn app.main:app --no-access-log
uv run celery -A app.workers.celery_app:celery_app worker --loglevel=INFO   # Windows: --pool=solo
uv run python -m app.cli create-admin --email admin@example.com
uv run pytest --cov=app && uv run ruff check . && uv run ruff format --check . && uv run mypy
```

## 12. Tests executed and real results

Run on the development box (Debian 13, Python 3.12 via uv, Docker 26.1.5, Compose 2.26.1),
test database `pgvector/pgvector:pg16`, test Redis with `requirepass`.

| Check | Result |
| --- | --- |
| `uv run pytest --cov=app` (with `TEST_DATABASE_URL`, password-protected `TEST_REDIS_URL`) | 128 passed; 94 % line coverage of `app/` |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 109 files already formatted (99 Python + 10 Markdown) |
| `uv run mypy` (strict) | Success: no issues found in 99 source files |
| `alembic upgrade head` on an empty database + `alembic check` | upgrade ran; "No new upgrade operations detected." |
| `docker compose build --no-cache` + `up -d` on fresh volumes, `.env` from `generate_env.py` | postgres/redis healthy, migrate exited 0, api and worker healthy |
| `scripts/smoke_test.py` against compose | passed: health, live, ready (DB + authenticated Redis), register, login, me, PDF + TXT processed to `completed` by the real worker, 415 for `.exe`, list, other user gets 404 on get/status/delete and an empty list, delete + 404, audit entries |
| `redis-cli ping` inside the redis container without credentials | `NOAUTH Authentication required.`; wrong password -> `WRONGPASS`; with `REDISCLI_AUTH` -> `PONG` |
| Container logs searched for the generated secret values | 0 occurrences each (Celery shows `redis://:**@redis:6379/0`) |
| Startup with missing / placeholder secrets or `STORAGE_BACKEND=s3` | fails with `SettingsError` / `StorageConfigurationError` naming the variable |

Test inventory (128): unit - security 5, config 12, upload validation 16, state machine 4,
storage 10, storage factory 3, request id 8, AI providers 7, generate_env 9; API - auth 14,
admin 5, documents 17, errors/request id 7, health 5; integration - processing 6.
Without `TEST_REDIS_URL`, two readiness tests are skipped.

## 13. Tests that failed

The final runs above had no failures. Failures seen during development and fixed:
- DIP1: `test_register_validates_password_length_without_echoing_it` failed because the
  sample password `short` also occurs in the error type `string_too_short`; the test now
  uses a distinctive value.
- DIP1: the compose `migrate` service timed out reaching Postgres because of stale
  `iptables-legacy` rules on the dev box (host issue, see dip3-handoff.md).
- DIP1: with Redis stopped an upload took about 3 minutes (Celery result-backend
  reconnects); fixed with `ignore_result=True` and socket timeouts (about 8 s, measured once).
- This revision: ruff `I001` (import order) in a new test, fixed with `ruff --fix`.

## 14. Known limitations

- `completed` means stored and integrity-verified; no content is extracted.
- Multipart bodies are fully received before the size limit applies; DOCX check is signature-only.
- No reprocess endpoint; broker failure at upload requires delete + re-upload.
- No rate limiting, lockout, refresh tokens or token revocation.
- Redis password visible as a `redis-server` argument via `docker inspect`.
- OpenAI adapters never called against the real API; Windows instructions not executed.
- `app/cli.py` (0 %) and `app/workers/tasks.py` (56 %) are only covered by manual/compose runs.
- Performance and scalability not measured yet.

## 15. Technical decisions

ADR-001 FastAPI; ADR-002 PostgreSQL + SQLAlchemy 2 + Alembic with pgvector; ADR-003
Celery + Redis with job state in PostgreSQL; ADR-004 storage abstraction; ADR-005 sync
database access. Also: settings derive URLs from parts so passwords live in one variable
each; the OpenAI SDK is imported lazily so no key or network is needed to start or test.

## 16. What DIP2 must not break

- Owner scoping in repositories and 404 for foreign resources.
- Upload ordering (file -> commit with job `queued` -> publish) and cleanup on failure.
- Session handling (`app/api/dependencies/db.py`, `app/db/session.py::session_scope`);
  repositories never commit.
- `DocumentProcessor` claim/finish logic (row lock, idempotency, safe messages) - extend
  via pipeline steps.
- Error envelope, request-id middleware, logging format and redaction.
- Secrets handling: `SecretStr`, no values in errors/logs, no OpenAI calls at startup,
  in health checks or in tests.
- Never edit migration `0001`; add new revisions.

## 17. Extension points for DIP2

| Need | Where |
| --- | --- |
| Extraction / OCR / chunking / embedding steps | new `PipelineStep` classes (e.g. `app/workers/steps/`), registered in `app/workers/pipeline.py::build_default_pipeline` after `IntegrityCheckStep`; raise `PermanentProcessingError(safe_message)` or `TransientProcessingError` |
| Passing text/chunks between steps | extend `PipelineContext` or persist via a session factory passed by `DocumentProcessor` |
| Embeddings / LLM | `app/ai/factory.py::get_embedding_provider(settings)` / `get_llm_provider(settings)`; tests fake the provider protocols |
| Vector tables | new model (e.g. `document_chunks`: document_id FK CASCADE, owner_id, ordinal, text, page/offsets, `embedding vector(N)`) + new Alembic revision with HNSW index; `uv add pgvector` for the SQLAlchemy type |
| Search, hybrid retrieval | `app/services/search_service.py`, `app/api/routes/search.py`; always filter by `owner_id`; combine `tsvector` full text with vector similarity |
| `/ask` with citations | `app/api/routes/ask.py`, `app/services/answer_service.py`; return chunk ids, document ids, pages/offsets |
| Router registration | `app/api/router.py` |
| Status meaning | once indexing exists, `completed` should mean indexed; update `DocumentStatus` docstring and README |
| Object storage | implement `StorageService`, add to `SUPPORTED_BACKENDS` in `app/storage/factory.py` |
