# ADR-002: PostgreSQL, SQLAlchemy 2.x and Alembic

**Status:** Accepted (DIP1)

## Context
The platform stores users, document metadata, processing jobs and audit logs, and
DIP2 will add chunk text and embeddings for similarity search.

## Decision
- **PostgreSQL 16** using the `pgvector/pgvector:pg16` image. The initial migration runs
  `CREATE EXTENSION IF NOT EXISTS vector`; no vector columns exist yet.
- **SQLAlchemy 2.x** typed ORM (`Mapped[...]`), psycopg 3 driver, native PostgreSQL ENUMs
  for statuses/roles, JSONB for audit metadata, UUID primary keys.
- **Alembic** for every schema change. Migrations are written/reviewed by hand and
  verified with `alembic check` (autogenerate diff against the models must be empty).
- A fixed constraint naming convention (`app/db/base.py`) keeps generated names stable.

## Alternatives
- **Separate vector database** (Qdrant, Weaviate): another service to operate and keep
  consistent with relational data; pgvector keeps metadata and vectors transactional.
- **SQLModel**: thinner layer over SQLAlchemy, but mixes API and persistence models.
- **`Base.metadata.create_all`**: no history, no safe upgrades.

## Consequences
- One database to back up, migrate and secure; vector search quality/performance with
  pgvector is *not measured yet* and must be evaluated in DIP2.
- ENUM changes need explicit migrations (`ALTER TYPE ... ADD VALUE`).
- The test suite runs the real migrations against a real PostgreSQL database.
