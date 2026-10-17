# ADR-001: FastAPI as the HTTP framework

**Status:** Accepted (DIP1)

## Context
The service exposes a JSON API with authentication, multipart uploads and generated
API documentation. Later stages add retrieval and question answering endpoints that
are mostly I/O bound and benefit from typed request/response models.

## Decision
Use FastAPI with Pydantic v2 models for all request and response bodies, dependency
injection for sessions, authentication and services, and the generated OpenAPI schema
(Swagger UI at `/docs`, ReDoc at `/redoc`).

## Alternatives
- **Django + DRF**: batteries included (admin, ORM, auth) but heavier, and its ORM would
  replace SQLAlchemy/Alembic, which suit pgvector and explicit transactions better.
- **Flask**: minimal, but validation, OpenAPI and DI would all be hand-assembled.
- **Litestar**: comparable feature set; smaller ecosystem and hiring familiarity.

## Consequences
- Request validation and OpenAPI docs come from the same type hints.
- Dependency overrides make tests substitute storage and the task queue without mocks
  of internals.
- FastAPI does not prescribe a project layout, so layering (routes -> services ->
  repositories) is a convention this repository must keep.
