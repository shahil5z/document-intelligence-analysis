# Testing

## Layout

| Directory | Tests | Needs |
| --- | --- | --- |
| `tests/unit` | 359 | nothing (no DB, Redis, network or model download); 1 test also uses `TEST_REDIS_URL` |
| `tests/api` | 139 | PostgreSQL 16 + pgvector via `TEST_DATABASE_URL`; 2 readiness tests also need `TEST_REDIS_URL` |
| `tests/integration` | 25 | PostgreSQL 16 + pgvector |
| **total** | **523** | |

Fakes (all in `tests/`): `HashingEmbeddingProvider` (deterministic 384-d embeddings),
`MockLLM`, `ReverseReranker`, `RecordingDispatcher` (replaces Celery). The rate limiter
uses the in-memory backend and is disabled by default in tests
(`RATE_LIMIT_ENABLED=false`); hardening tests turn it on explicitly. Without
`TEST_DATABASE_URL` the database fixtures skip, so `uv run pytest` works on a machine
with no services. The suite never downloads a model and never calls a real LLM.

## Commands

```bash
uv sync --frozen
uv run ruff check . && uv run ruff format --check . && uv run mypy app tests scripts
docker run -d --name dip-test-db -e POSTGRES_USER=dip -e POSTGRES_PASSWORD=dip \
  -e POSTGRES_DB=dip_test -p 5433:5432 pgvector/pgvector:pg16
export TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test
export TEST_REDIS_URL='redis://:<password>@localhost:6380/0'      # optional
uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=90
```

End to end against a running compose stack:

```bash
uv run python scripts/smoke_test.py --base-url http://localhost:8000              # /ask expected 503 without a key
docker compose -f docker-compose.yml -f docker-compose.stub-llm.yml up -d --wait
uv run python scripts/smoke_test.py --ask-expect answer --check-rate-limit       # with the local stub LLM
uv run python scripts/smoke_test.py --real-llm                                   # explicit, real model (costs a few calls)
```

Manual checklist for Windows: [manual-testing.md](manual-testing.md).

## Coverage of risk areas

| Area | Tests |
| --- | --- |
| Body limits: Content-Length 413 before reading, chunked bodies, upload streaming | `tests/unit/test_http_hardening.py`, smoke test |
| Rate limits, fail-closed credentials / fail-open elsewhere when Redis is down, real Redis counter | `tests/unit/test_http_hardening.py`, `tests/unit/test_rate_limit.py` |
| Production config validation, stale-job timeout rule | `tests/unit/test_production_config.py`, `tests/integration/test_stale_jobs.py` |
| `/ask` evidence gate (no LLM call), owner scoping, LLM errors -> 503, prompt injection, forged citations | `tests/unit/test_answer_service.py`, `tests/unit/test_llm_provider.py`, `tests/api/test_ask.py` |
| Metrics labels, LLM usage logging, pgvector version policy | `tests/unit/test_observability.py`, `tests/api/test_health.py` |
| Celery adapter: retries, final attempt -> failed, beat schedule | `tests/unit/test_worker_adapters.py` |
| Soft timeout, bounded redelivery, DB outage while finishing | `tests/integration/test_reliability.py` |
| Stale-job reconciler (processing/retrying, locked rows skipped, CLI) | `tests/integration/test_stale_jobs.py` |
| Cross-user matrix, tampered/deleted-user tokens, hostile filenames, 413 without DB row, concurrent reprocess -> one 202 + one 409 | `tests/api/test_security_matrix.py` |
| `generate_env.py` create / merge (byte-preserving, CRLF, idempotent, no values printed) | `tests/unit/test_generate_env.py` |

## Recorded results

| Run | Environment | Result |
| --- | --- | --- |
| `final` before the final-phase changes | Linux box, Python 3.12.15, PostgreSQL 16.15 + pgvector 0.8.7 | 333 passed, 0 skipped, 95% coverage |
| **`final` after the final-phase changes** | same, plus Redis 7.4.11 with password (`TEST_REDIS_URL`) | **364 passed, 0 skipped, 96% coverage** (3370 statements, 148 missed), 57.7 s |
| **`main` after the ONNX merge** (2026-10-20) | Linux box, Python 3.12.15, PostgreSQL 16 + pgvector, Redis 7 with password, no S3 server | **512 passed, 11 skipped (S3), 96% coverage** (4320 statements, 185 missed), 74.5 s |
| DB-backed tests against pgvector 0.6.2 (fallback path) | PostgreSQL 16 + pgvector 0.6.2 | see [verification report](history/final-project-report.md#7-verification-results) |
| DIP3, historical | Windows 11, PostgreSQL 16.2 + pgvector 0.6.2 | 330 passed, 3 skipped, 95% coverage (not repeated) |

ruff check: clean; ruff format: 170 files formatted; mypy (strict): no issues in 147
source files. The CI workflow was linted with actionlint 1.7.7 (exit 0) but has never
run on GitHub.

### Production phase (2026-10-18, Linux build box)

- `pytest --cov=app` with PostgreSQL 16 + pgvector 0.8.7, password Redis and a local
  S3-compatible server (`TEST_S3_*`): **414 passed, 0 skipped, 96%**.
- `tests/unit` in the arm64 image under QEMU: 256 passed, 12 skipped (no S3 server /
  Redis in that container).
- Frontend: `npm run lint`, `npm run typecheck`, `npm run build` clean; Playwright
  `frontend/e2e/full-flow.spec.ts` 10 passed against the production-like stack
  (`scripts/e2e_prod_local.sh`).
- `scripts/production_smoke_test.py` 13/13 checks against the local Caddy endpoint.
- Not run: GitHub Actions, Windows, real OpenAI, real Oracle/Vercel.
