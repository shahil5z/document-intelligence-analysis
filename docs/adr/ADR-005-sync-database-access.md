# ADR-005: Synchronous SQLAlchemy sessions and `def` routes

**Status:** Accepted (DIP1)

## Context
FastAPI supports both `async def` routes with an async driver and plain `def` routes
executed in a threadpool. The Celery worker is synchronous.

## Decision
Use synchronous SQLAlchemy 2.x (psycopg 3) everywhere and declare routes and
dependencies as `def`. FastAPI runs them in its threadpool, so the event loop is not
blocked. The same models, repositories and session factory are shared by API, worker
and CLI.

Transaction rules:
- One session per request (`app/api/dependencies/db.py`), torn down with
  `scope="function"` before the response is sent.
- Services call `commit()` explicitly at their boundaries; repositories never commit.
- Any exception rolls back; the session is always closed.

## Alternatives
- **Async SQLAlchemy + asyncpg**: better for very high concurrency on I/O-bound
  routes, but needs a second (sync) code path for Celery or an async task runner,
  plus care with lazy loading. Not justified before any load has been measured.

## Consequences
- Simple, uniform code; one repository implementation.
- Concurrency per API process is bounded by the threadpool size and DB pool
  (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`). Throughput is *not measured yet*.
- Long-running external calls added in DIP2 (embedding APIs, LLM calls on `/ask`)
  should be evaluated; `/ask` may justify an async route with an async HTTP client
  while keeping DB access sync.
