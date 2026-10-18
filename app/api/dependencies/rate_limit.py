"""Rate-limit dependencies.

* ``limit_by_ip(scope)``: anonymous endpoints (register, login). The client address is
  ``request.client.host``; behind a proxy run uvicorn with ``--proxy-headers`` and a
  correct ``--forwarded-allow-ips`` so this is the real client, not the proxy.
* ``limit_by_user(scope)``: authenticated endpoints, keyed by user id (runs after auth,
  which FastAPI caches per request, so the user is loaded once).
* ``enforce_rate_limit``: for keys only known inside the route (login per e-mail).

Redis outage policy (``FAIL_CLOSED_SCOPES``): register/login reject with 503 so a broken
limiter never means unlimited password guessing; all other scopes are allowed with a
warning log and ``dip_rate_limiter_errors_total{decision="fail_open"}``.

The limiter lives on ``app.state.rate_limiter`` (``None`` when disabled); rates come from
``app.state.settings`` so each app instance (and each test) is isolated.
"""

import logging
from collections.abc import Callable
from typing import Literal

from fastapi import Request

from app.api.dependencies.auth import CurrentUser, UploadUser
from app.core.config import Settings
from app.core.errors import RateLimitedError, ServiceUnavailableError
from app.core.metrics import RATE_LIMITED, RATE_LIMITER_ERRORS
from app.core.rate_limit import RateLimiter, RateLimiterUnavailableError, parse_rate

logger = logging.getLogger(__name__)

RateScope = Literal["register", "login", "login_per_email", "upload", "search", "ask", "reprocess"]

# Scopes that protect credentials: without a working limiter they are refused (503).
FAIL_CLOSED_SCOPES: frozenset[RateScope] = frozenset({"register", "login", "login_per_email"})
LIMITER_UNAVAILABLE_MESSAGE = "Sign-in and registration are temporarily unavailable; retry later"
_FAIL_CLOSED_RETRY_AFTER_SECONDS = 5


def _rate_setting(settings: Settings, scope: RateScope) -> str:
    value: str = getattr(settings, f"rate_limit_{scope}")
    return value


def enforce_rate_limit(request: Request, scope: RateScope, identifier: str) -> None:
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    settings: Settings = request.app.state.settings
    try:
        decision = limiter.hit(scope, identifier, parse_rate(_rate_setting(settings, scope)))
    except RateLimiterUnavailableError as exc:
        fail_closed = scope in FAIL_CLOSED_SCOPES
        decision_label = "fail_closed" if fail_closed else "fail_open"
        RATE_LIMITER_ERRORS.labels(scope, decision_label).inc()
        logger.warning(
            "rate_limit.backend_unavailable",
            extra={"scope": scope, "decision": decision_label, "error_type": str(exc)},
        )
        if fail_closed:
            raise ServiceUnavailableError(
                LIMITER_UNAVAILABLE_MESSAGE,
                headers={"Retry-After": str(_FAIL_CLOSED_RETRY_AFTER_SECONDS)},
            ) from exc
        return
    if not decision.allowed:
        RATE_LIMITED.labels(scope).inc()
        raise RateLimitedError(decision.retry_after_seconds)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_by_ip(scope: RateScope) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        enforce_rate_limit(request, scope, client_ip(request))

    return dependency


def limit_by_user(scope: RateScope) -> Callable[..., None]:
    def dependency(request: Request, user: CurrentUser) -> None:
        enforce_rate_limit(request, scope, str(user.id))

    return dependency


def limit_by_upload_user(scope: RateScope) -> Callable[..., None]:
    """Like ``limit_by_user`` but also accepts the upload-only token."""

    def dependency(request: Request, user: UploadUser) -> None:
        enforce_rate_limit(request, scope, str(user.id))

    return dependency
