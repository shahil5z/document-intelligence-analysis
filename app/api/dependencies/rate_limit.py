"""Rate-limit dependencies.

* ``limit_by_ip(scope)``: anonymous endpoints (register, login). The client address is
  ``request.client.host``; behind a proxy run uvicorn with ``--proxy-headers`` and a
  correct ``--forwarded-allow-ips`` so this is the real client, not the proxy.
* ``limit_by_user(scope)``: authenticated endpoints, keyed by user id (runs after auth,
  which FastAPI caches per request, so the user is loaded once).
* ``enforce_rate_limit``: for keys only known inside the route (login per e-mail).

The limiter lives on ``app.state.rate_limiter`` (``None`` when disabled); rates come from
``app.state.settings`` so each app instance (and each test) is isolated.
"""

from collections.abc import Callable
from typing import Literal

from fastapi import Request

from app.api.dependencies.auth import CurrentUser
from app.core.config import Settings
from app.core.errors import RateLimitedError
from app.core.metrics import RATE_LIMITED
from app.core.rate_limit import RateLimiter, parse_rate

RateScope = Literal["register", "login", "login_per_email", "upload", "search", "ask", "reprocess"]


def _rate_setting(settings: Settings, scope: RateScope) -> str:
    value: str = getattr(settings, f"rate_limit_{scope}")
    return value


def enforce_rate_limit(request: Request, scope: RateScope, identifier: str) -> None:
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    settings: Settings = request.app.state.settings
    decision = limiter.hit(scope, identifier, parse_rate(_rate_setting(settings, scope)))
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
