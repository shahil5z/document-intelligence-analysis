"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.request_context import REQUEST_ID_HEADER
from app.db.session import get_engine
from app.storage.factory import check_storage_backend

API_DESCRIPTION = """
Backend foundation for a document intelligence platform.

* **Auth** - register, log in (JSON or OAuth2 form), JWT bearer tokens, user/admin roles.
* **Documents** - validated uploads (PDF, DOCX, TXT), per-user isolation, deletion.
* **Processing** - each upload creates a job executed asynchronously by a Celery worker.
  The worker currently verifies the stored file's integrity; text extraction, chunking,
  embeddings, search and question answering are planned and **not implemented yet**.
* **Audit** - security-relevant actions are recorded and queryable.

Every response carries an `X-Request-ID` header; errors use a single envelope:
`{"error": {"code", "message", "request_id", "details?"}}`.
"""

OPENAPI_TAGS = [
    {"name": "auth", "description": "Registration, login and the current user."},
    {"name": "documents", "description": "Upload, list, inspect and delete your documents."},
    {"name": "audit", "description": "Your own audit trail."},
    {"name": "admin", "description": "Administrator-only endpoints."},
    {"name": "health", "description": "Liveness and readiness probes."},
]


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    get_engine().dispose()


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    # Order: the last added middleware runs first. Request context must wrap everything
    # (including CORS responses) so every response has a request id.
    # Rate limiting (DIP3) belongs here, after CORS and inside the request context.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestContextMiddleware)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    check_storage_backend(settings)
    configure_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=_lifespan,
    )
    _register_middleware(app, settings)
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
