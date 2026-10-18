# Testing

## Layout

| Directory | Tests (DIP3) | Needs |
| --- | --- | --- |
| `tests/unit` | 217 | nothing (no DB, Redis, network or model download) |
| `tests/api` | 96 | PostgreSQL 16 + pgvector via `TEST_DATABASE_URL`; 2 readiness tests also need `TEST_REDIS_URL` |
| `tests/integration` | 20 | PostgreSQL 16 + pgvector |

Fakes (all in `tests/`): `HashingEmbeddingProvider` (deterministic 384-d embeddings),
`MockLLM`, `ReverseReranker`, `RecordingDispatcher` (replaces Celery). The rate limiter
uses the in-memory backend and is disabled by default in tests
(`RATE_LIMIT_ENABLED=false`); hardening tests turn it on explicitly.

Without `TEST_DATABASE_URL` the database fixtures skip, so `uv run pytest` works on a
machine with no services.

## Commands

```bash
uv sync --frozen
uv run pytest                          # unit only when TEST_DATABASE_URL is unset
docker run -d --name dip-test-db -e POSTGRES_USER=dip -e POSTGRES_PASSWORD=dip \
  -e POSTGRES_DB=dip_test -p 5433:5432 pgvector/pgvector:pg16
export TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test
uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=90
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

## DIP3 coverage of new risk areas

| Area | Tests |
| --- | --- |
| Body limits (Content-Length, chunked, upload streaming) | `tests/unit/test_http_hardening.py` |
| Rate limits (register per IP, login per email incl. OAuth form, search per user, disabled) | `tests/unit/test_http_hardening.py`, `tests/unit/test_rate_limit.py` |
| Production config validation | `tests/unit/test_production_config.py` |
| `/ask` evidence gate, owner scoping, LLM errors -> 503, prompt injection, forged citations | `tests/unit/test_answer_service.py` |
| Metrics labels, LLM usage logging, pgvector version detection | `tests/unit/test_observability.py` |
| Celery adapter: retries, timeouts, request-id binding, dispatcher errors | `tests/unit/test_worker_adapters.py` |
| Soft timeout, bounded redelivery, DB outage while finishing, retry metric | `tests/integration/test_reliability.py` |
| Cross-user matrix, tampered/deleted-user tokens, hostile filenames, 413 without DB row, double reprocess 409 | `tests/api/test_security_matrix.py` |

## Recorded results (DIP3, Windows 11, Python 3.12.15)

| Run | Result |
| --- | --- |
| Baseline before DIP3, PostgreSQL 16.2 + pgvector 0.6.2 | 228 passed, 19 failed, 2 skipped, 93% coverage. 17 failures: `SET LOCAL hnsw.iterative_scan` is unknown to pgvector < 0.8; 2: POSIX-only assumptions |
| After DIP3, same database | **330 passed, 3 skipped, 95% coverage** (skips: 2 Redis readiness tests without `TEST_REDIS_URL`, 1 symlink test without privilege) |
| After DIP3, no database | 216 passed, 117 skipped, 79% coverage |

Not run locally: tests against pgvector >= 0.8 (the `iterative_scan` path), tests with a
real Redis, the CI workflow. The DIP2 handoff records 247 passed / 2 skipped on Linux
with pgvector 0.8; that run was not repeated.
