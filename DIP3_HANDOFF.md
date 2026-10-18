# DIP3 handoff: tests, CI/CD, observability, rate limiting, hardening

## Verified state at the end of DIP1

Full results, the test inventory and failures seen during development are in
[DIP1_HANDOFF.md section 12-13](DIP1_HANDOFF.md#12-tests-executed-and-real-results).
Summary of the last run: 128 tests passed (94 % line coverage of `app/`), ruff check and
format clean, mypy strict clean, `alembic check` clean, compose stack healthy from a
`--no-cache` build on fresh volumes, smoke test passed, Redis rejects unauthenticated
commands. Without `TEST_REDIS_URL`, two readiness tests are skipped.

### Missing tests

- Celery task adapter (`app/workers/tasks.py`, 56 % covered) and `CeleryDocumentTaskDispatcher`
  against a real broker (exercised only by the manual compose smoke test).
- `app/cli.py` (0 % covered; exercised manually in compose).
- Concurrency: two deliveries of one task at once (row lock), duplicate upload race (unique
  constraint path).
- Storage delete failure after DB delete; DB commit failure after file save.
- Token for a deleted user; tokens with tampered `role` claim.
- OpenAI adapters against the real API (only a fake client is used; no key on the dev box).
- Windows host run (README notes are untested).
- Load / performance tests: not measured yet.

## CI/CD (to build)

Suggested GitHub Actions jobs:
1. `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy`.
2. Tests with a `pgvector/pgvector:pg16` service container and `redis:7-alpine` started
   with `--requirepass`; set `TEST_DATABASE_URL` and `TEST_REDIS_URL=redis://:<pw>@localhost:6379/0`
   from CI secrets or per-run random values. No `OPENAI_API_KEY` is needed.
3. `alembic upgrade head && alembic check` against an empty database.
4. `docker build`, image scan (e.g. Trivy), optional compose smoke test: create `.env`
   with `python scripts/generate_env.py`, `docker compose up -d`, `scripts/smoke_test.py`.
5. Secret scanning of tracked files (e.g. gitleaks); `.env` and `/env` are git-ignored.

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
- Redis password is passed on the `redis-server` command line (visible via `docker inspect`);
  prefer a mounted config file or ACL file.
- Redis has no TLS; Postgres connections are not TLS either (fine on the compose network only).

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
