# DIP3 handoff: tests, CI/CD, observability, rate limiting, hardening

## Verified state at the end of DIP1

All numbers below come from actual runs on the development box (Debian 13, Docker 26.1.5,
Compose 2.26.1, Python 3.12 via uv).

| Check | Command | Result |
| --- | --- | --- |
| Tests | `TEST_DATABASE_URL=... TEST_REDIS_URL=... uv run pytest --cov=app` | 99 passed; 94 % line coverage of `app/` |
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 98 files already formatted (89 Python + 9 Markdown) |
| Types | `uv run mypy` (strict, pydantic plugin, `app tests alembic scripts`) | no issues in 89 source files |
| Migrations | `alembic upgrade head`, `alembic check`, `downgrade base`, `upgrade head` | clean, no diff |
| Compose | `docker compose up --build -d` | postgres/redis healthy, migrate exit 0, api/worker healthy |
| E2E | `python scripts/smoke_test.py` | passed (register, login, PDF + TXT processed by real worker, 415, list, delete, audit) |

Without `TEST_REDIS_URL`, `test_readiness_ok_with_real_redis` is skipped.

### Test inventory (99 tests)

| File | Tests | Covers |
| --- | --- | --- |
| `tests/unit/test_security.py` | 5 | Argon2 hash/verify/salting, JWT claims, expiry, wrong secret, wrong type |
| `tests/unit/test_config.py` | 4 | secret length, `*` CORS rejected, production placeholder secret, CSV parsing |
| `tests/unit/test_upload_validation.py` | 16 | filename sanitising, type allow-list, magic bytes, streamed size limit, empty file |
| `tests/unit/test_state_machine.py` | 4 | transition tables complete, happy path, illegal transitions, retry path |
| `tests/unit/test_storage.py` | 10 | round trip, traversal/malformed keys, symlink escape, no partial files |
| `tests/unit/test_request_context.py` | 8 | request-id acceptance/replacement |
| `tests/api/test_auth.py` | 14 | register, role injection ignored, duplicate 409, 422 without echo, login ok/fail/unknown, OAuth2 form, inactive 403, `/auth/me`, 401 variants, audit |
| `tests/api/test_admin.py` | 5 | 403 for users, 401 anonymous, list users, filter audit logs, `/audit-logs/me` scoping |
| `tests/api/test_documents.py` | 17 | upload PDF/TXT/DOCX, no storage leak, 401, 415 extension/magic, 413 + cleanup, empty 400, duplicate 409, enqueue failure, pagination + cap, isolation, detail, foreign 404, delete + foreign delete 404, status |
| `tests/api/test_errors_and_request_id.py` | 7 | request-id generation/reuse/replacement, 404/422/500 envelopes, CORS |
| `tests/api/test_health.py` | 3 | liveness, readiness 503 with unreachable Redis, readiness 200 with real Redis |
| `tests/integration/test_processing.py` | 6 | complete + idempotent redelivery, missing file, tampered file, transient retry then final failure, unexpected error not leaked, unknown job |

### Missing tests

- Celery task adapter (`app/workers/tasks.py`, 56 % covered) and `CeleryDocumentTaskDispatcher`
  against a real broker (exercised only by the manual compose smoke test).
- `app/cli.py` (0 % covered; exercised manually in compose).
- Concurrency: two deliveries of one task at once (row lock), duplicate upload race (unique
  constraint path).
- Storage delete failure after DB delete; DB commit failure after file save.
- Token for a deleted user; tokens with tampered `role` claim.
- Load / performance tests: not measured yet.

## CI/CD (to build)

Suggested GitHub Actions jobs:
1. `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy`.
2. Tests with a `pgvector/pgvector:pg16` service container and `redis:7-alpine`;
   `TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5432/dip_test`.
3. `alembic upgrade head && alembic check` against an empty database.
4. `docker build`, image scan (e.g. Trivy), optional compose smoke test running
   `scripts/smoke_test.py`.

## Rate limiting

Not implemented. Hook: `app/main.py::_register_middleware` (add inside
`RequestContextMiddleware` so 429 responses carry a request id; use the `rate_limited`
error code already mapped in `app/core/errors.py`). Priorities: `/auth/login`,
`/auth/token`, `/auth/register` (per IP + per email), `POST /documents` (per user).
Redis is already available for counters.

## Observability

- Logs: JSON to stdout (`app/core/logging.py`), request ids propagate to worker logs.
- Missing: metrics (request latency/status, job durations, queue depth), tracing
  (OpenTelemetry for FastAPI, SQLAlchemy, Celery), log shipping, alerting.
- `RequestContextMiddleware` (`app/core/middleware.py`) already measures `duration_ms`
  per request; a metrics exporter can hook there.

## Security hardening areas

- Request body limit before multipart parsing (proxy `client_max_body_size` or ASGI middleware).
- Account lockout / login throttling; refresh tokens and revocation (`jti` is already issued).
- Deeper DOCX validation, malware scanning, PDF sanitising.
- Password policy beyond length (12-128 chars today), breached-password check.
- Security headers (HSTS, CSP for docs pages) at the proxy or middleware.
- Audit log retention and immutability (DB permissions); PII review of audit metadata
  (original filenames are stored).
- Secrets via a secret manager; JWT key rotation (consider asymmetric keys).

## Container security

- Current: two-stage Dockerfile, `python:3.12-slim`, uv-installed locked dependencies,
  non-root user uid 10001, healthcheck, Postgres/Redis not published to the host.
- Missing: pinned base image digests, image scanning, read-only root filesystem,
  dropped capabilities / `no-new-privileges` in compose, resource limits, SBOM.

## Docker notes from DIP1

The dev box had stale `iptables-legacy` rules (FORWARD policy DROP) that blocked traffic
between containers on compose networks; it was worked around on that box with
`iptables-legacy -I DOCKER-USER -i br-+ -o br-+ -j ACCEPT`. This is a host quirk, not a
project requirement.
