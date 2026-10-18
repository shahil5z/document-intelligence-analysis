# DIP3 handoff: production hardening

Status on 2026-10-18: implemented in the working tree of branch `dip2` (**uncommitted**,
no remote). Verified on Windows 11 with Python 3.12.15, a local PostgreSQL 16.2 +
pgvector 0.6.2 (no Docker) and no Redis. Everything that needs Docker, Redis, a real
LLM or GitHub is marked **NOT VERIFIED - Docker unavailable** or **NOT VERIFIED**.

DIP1/DIP2 state: [DIP1_HANDOFF.md](DIP1_HANDOFF.md), [DIP2_HANDOFF.md](DIP2_HANDOFF.md).
This file replaces the earlier DIP3 plan.

## Discrepancies found in the audit

- DIP2 handoff: 247 passed / 2 skipped. On this machine the unchanged suite gave
  228 passed, 19 failed, 2 skipped (93%): 17 failures because pgvector 0.6.2 does not
  know `hnsw.iterative_scan` (needs >= 0.8), 2 because of POSIX-only test assumptions.
  Fixed by runtime version detection and platform skips.
- The suite exited without PostgreSQL even for unit tests; fixed (DB fixtures skip).
- README Windows notes had never been executed; now partly exercised (tests only).
- LLM token usage was silently redacted in logs (`token` rule); renamed fields.
- A new LLM HTTP client was created per `/ask` request and never closed; now cached.

## What changed

New: `app/core/rate_limit.py`, `app/core/metrics.py`, `app/api/dependencies/rate_limit.py`,
`app/api/routes/metrics.py`, `.github/workflows/ci.yml`, `tests/api/conftest.py`,
`tests/integration/conftest.py`, `tests/unit/test_http_hardening.py`,
`tests/unit/test_rate_limit.py`, `tests/unit/test_production_config.py`,
`tests/unit/test_answer_service.py`, `tests/unit/test_observability.py`,
`tests/unit/test_worker_adapters.py`, `tests/integration/test_reliability.py`,
`tests/api/test_security_matrix.py`, `docs/testing.md`, `docs/observability.md`,
`docs/performance.md`, `docs/deployment.md`.

Modified: `app/core/{config,errors,middleware}.py`, `app/main.py`,
`app/api/responses.py`, `app/api/routes/{auth,documents,search}.py`,
`app/services/{answer,document,search}_service.py`,
`app/db/repositories/{chunks,documents}.py`, `app/ai/{llm,factory}.py`,
`app/workers/{celery_app,pipeline,processing,tasks}.py`, `tests/conftest.py`,
`tests/unit/test_generate_env.py`, `tests/unit/test_storage.py`, `pyproject.toml` +
`uv.lock` (`prometheus-client>=0.21`, resolved 0.26.0), `.env.example`,
`docker-compose.yml`, `Dockerfile`, `README.md`, `docs/architecture.md`,
`docs/SECURITY.md`, `docs/portfolio.md`, this file.

## Results (real runs)

| Check | Result |
| --- | --- |
| `pytest --cov=app` with PostgreSQL | **330 passed, 3 skipped, 95%** (skips: 2 need `TEST_REDIS_URL`, 1 symlink privilege) |
| `pytest` without any database | 216 passed, 117 skipped |
| `ruff check .`, `ruff format --check .` | all checks passed; 165 files already formatted |
| `mypy` (strict) | no issues in 146 source files |
| `alembic upgrade head` + `alembic check` | no new upgrade operations |
| `pip-audit` on `uv export` | no known vulnerabilities; `torch` (CPU index build) skipped as not on PyPI |
| `ci.yml` | parsed with PyYAML; **never run** |
| Live uvicorn on 127.0.0.1 (PostgreSQL up, Redis down) | `/health/live` 200 with request id + security headers; `/health/ready` 503 (database ok, redis error); register/login/upload/status/search OK; upload with broker down -> `failed` with the fixed message; 2 MiB JSON -> 413; third login for one email -> 429; `/metrics` labels are route templates and contain no document id; no secret, password or email in 27 log lines |

## Checklist

| Item | Status |
| --- | --- |
| Unit/API/security/cross-user/prompt-injection/failure tests without keys or Docker | PASS (API/integration need PostgreSQL) |
| Upload / request body limits before parsing | PASS |
| Filename sanitisation | PASS (existing, now covered by hostile-name tests) |
| CORS (explicit origins, https in production) | PASS |
| Production config validation | PASS |
| Error leakage (generic 500, no values in config errors) | PASS |
| Rate limiting | PARTIAL - in-memory backend verified; Redis backend only tested for fail-open against an unreachable Redis; counting in real Redis **NOT VERIFIED - Docker unavailable** |
| Structured logging + X-Request-ID | PASS |
| Prometheus metrics (API) | PASS |
| Worker metrics exporter | NOT VERIFIED - Docker unavailable (prefork not on Windows) |
| `/health/live`, `/health/ready` | PASS (ready with real Redis: NOT VERIFIED) |
| Celery retry / idempotency / partial failure | PASS in tests; with a real broker and worker: NOT VERIFIED - Docker unavailable |
| pgvector >= 0.8 iterative scan path | NOT VERIFIED (only 0.6.2 fallback ran) |
| Dockerfile / compose fixes | PARTIAL - static review only; NOT VERIFIED - Docker unavailable |
| CI workflow | PARTIAL - written and YAML-valid; NOT VERIFIED (never run) |
| Docs | PASS |
| Tracing | NOT IMPLEMENTED |
| Image scanning, digest pinning, read-only rootfs | NOT IMPLEMENTED |
| Stuck-job reaper | NOT IMPLEMENTED |
| Real LLM / real reranker | NOT VERIFIED |

## Known limitations

- Rate limits fail open when Redis is down, are fixed-window, and for uploads run after
  the (size-limited) body was received.
- If the last allowed attempt cannot write its result, the job stays `processing`.
- Redis password visible in the `redis-server` command line.
- Performance not measured ([docs/performance.md](docs/performance.md)).

## Secrets

`.env` is git-ignored (`.gitignore:2`), not tracked and never committed (`git log --all`
empty for `.env` and `env`). Key names only: APP_NAME, APP_ENV, DEBUG, LOG_LEVEL,
API_PORT, JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES, POSTGRES_HOST,
POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, REDIS_HOST, REDIS_PORT,
REDIS_DB, REDIS_PASSWORD, STORAGE_BACKEND, STORAGE_PATH, MAX_UPLOAD_SIZE_BYTES,
ALLOWED_EXTENSIONS, ALLOWED_CONTENT_TYPES, CORS_ALLOWED_ORIGINS, OPENAI_API_KEY. The new
DIP3 variables are not in `.env`; their defaults apply.

## What remains to verify after Docker installation

```bash
# 1. Stack
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps                                   # api healthy, migrate exited 0
docker compose exec api id -u                       # expect 10001
curl -fsS http://localhost:8000/health/ready        # expect 200, database+redis ok
curl -fsS http://localhost:8000/metrics | grep dip_http_requests_total
docker compose exec worker python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:9100/metrics').read()[:300])"
uv run python scripts/smoke_test.py

# 2. Full tests with pgvector >= 0.8 and authenticated Redis
docker run -d --name dip-test-db -e POSTGRES_USER=dip -e POSTGRES_PASSWORD=dip -e POSTGRES_DB=dip_test -p 5433:5432 pgvector/pgvector:pg16
docker run -d --name dip-test-redis -p 6380:6379 redis:7-alpine redis-server --requirepass testpass
export TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test
export TEST_REDIS_URL=redis://:testpass@localhost:6380/0
uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=90   # expect 0 skipped except platform ones
DATABASE_URL=$TEST_DATABASE_URL uv run alembic downgrade base
DATABASE_URL=$TEST_DATABASE_URL uv run alembic upgrade head
DATABASE_URL=$TEST_DATABASE_URL uv run alembic check

# 3. Redis rate limiter against real Redis (expect 429 on the 6th call)
for i in 1 2 3 4 5 6; do curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"email":"x@example.com","password":"wrong-password-1"}'; done

# 4. CI: commit, add a remote, push, and watch .github/workflows/ci.yml (user decision)
```
