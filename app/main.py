"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.metrics import router as metrics_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import MemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.core.request_context import REQUEST_ID_HEADER
from app.db.session import get_engine
from app.storage.factory import check_storage_backend

API_DESCRIPTION = """
Backend foundation for a document intelligence platform.

* **Auth** - register, log in (JSON or OAuth2 form), JWT bearer tokens, user/admin roles.
* **Documents** - validated uploads (PDF, DOCX, TXT), per-user isolation, deletion.
* **Processing** - each upload creates a job executed asynchronously by a Celery worker:
  integrity check, text extraction (PDF/DOCX/TXT, no OCR), normalization, token-aware
  chunking, local embeddings and indexing in PostgreSQL (pgvector + full-text).
* **Search** - semantic, keyword or hybrid (RRF) retrieval over your completed documents.
* **Ask** - grounded answers with citations validated against the retrieved passages.
* **Audit** - security-relevant actions are recorded and queryable.

Every response carries an `X-Request-ID` header; errors use a single envelope:
`{"error": {"code", "message", "request_id", "details?"}}`.
"""

OPENAPI_TAGS = [
    {"name": "auth", "description": "Registration, login and the current user."},
    {"name": "documents", "description": "Upload, list, inspect and delete your documents."},
    {"name": "search", "description": "Retrieval and question answering over your documents."},
    {"name": "audit", "description": "Your own audit trail."},
    {"name": "admin", "description": "Administrator-only endpoints."},
    {"name": "health", "description": "Liveness and readiness probes."},
]


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    get_engine().dispose()


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    # Order: the last added middleware runs first (outermost). Resulting chain:
    # RequestContext -> SecurityHeaders -> BodySizeLimit -> CORS -> routes, so 413s,
    # 500s and CORS responses all carry a request id, security headers and metrics.
    # Rate limits are route dependencies (app/api/dependencies/rate_limit.py) because
    # per-user limits need the authenticated user.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
    )
    app.add_middleware(
        BodySizeLimitMiddleware,
        default_limit=settings.max_request_body_bytes,
        upload_limit=settings.max_upload_size_bytes + settings.upload_body_overhead_bytes,
    )
    if settings.security_headers_enabled:
        app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(RequestContextMiddleware, metrics_enabled=settings.metrics_enabled)


def build_rate_limiter(settings: Settings) -> RateLimiter | None:
    if not settings.rate_limit_enabled:
        return None
    if settings.rate_limit_backend == "memory":
        return MemoryRateLimiter()
    return RedisRateLimiter(settings.get_redis_url())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    check_storage_backend(settings)
    configure_logging(settings.log_level)
    docs = settings.docs_enabled
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=_lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.rate_limiter = build_rate_limiter(settings)
    _register_middleware(app, settings)
    register_exception_handlers(app)
    app.include_router(api_router)
    if settings.metrics_enabled:
        app.include_router(metrics_router)
    return app


app = create_app()
