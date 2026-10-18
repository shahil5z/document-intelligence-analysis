"""Rate-limit dependencies.

* ``limit_by_ip(*scopes)``: anonymous endpoints (register, login). The client address is
  ``request.client.host``; behind a proxy run uvicorn with ``--proxy-headers`` and a
  correct ``--forwarded-allow-ips`` so this is the real client, not the proxy.
* ``limit_by_user(*scopes)``: authenticated endpoints, keyed by user id (runs after auth,
  which FastAPI caches per request, so the user is loaded once).
* ``enforce_rate_limit``: for keys only known inside the route (login per e-mail).

Redis outage policy (``FAIL_CLOSED_SCOPES``): register/login/demo reject with 503 so a broken
limiter never means unlimited password guessing; all other scopes are allowed with a
warning log and ``dip_rate_limiter_errors_total{decision="fail_open"}``.

The limiter lives on ``app.state.rate_limiter`` (``None`` when disabled); rates come from
``app.state.settings`` so each app instance (and each test) is isolated.
"""

import hmac
import ipaddress
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

RateScope = Literal[
    "register",
    "register_daily",
    "login",
    "login_per_email",
    "upload",
    "upload_daily",
    "upload_token",
    "search",
    "ask",
    "ask_daily",
    "reprocess",
    "demo",
    "demo_global",
]

# Scopes that protect credentials or create accounts: without a working limiter they
# are refused (503). Demo accounts cost LLM tokens, so they fail closed too.
FAIL_CLOSED_SCOPES: frozenset[RateScope] = frozenset(
    {"register", "register_daily", "login", "login_per_email", "demo", "demo_global"}
)
# Identifier for limits shared by all clients (demo_global).
GLOBAL_IDENTIFIER = "global"
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


CLIENT_IP_HEADER = "x-dip-client-ip"
CLIENT_IP_SECRET_HEADER = "x-dip-client-secret"  # noqa: S105  (a header name)


def client_ip(request: Request) -> str:
    """The client address used for per-IP limits.

    A request that carries the configured ``CLIENT_IP_HEADER_SECRET`` may name the real
    client in ``X-DIP-Client-IP`` (the BFF does, because to the API every browser request
    comes from the BFF's server). Anyone else's header is ignored, so it cannot be used to
    dodge limits.
    """
    peer = request.client.host if request.client else "unknown"
    settings: Settings = request.app.state.settings
    secret = settings.client_ip_header_secret
    if secret is None or not secret.get_secret_value():
        return peer
    presented = request.headers.get(CLIENT_IP_SECRET_HEADER, "")
    if not hmac.compare_digest(presented.encode(), secret.get_secret_value().encode()):
        return peer
    claimed = request.headers.get(CLIENT_IP_HEADER, "").strip()
    try:
        return str(ipaddress.ip_address(claimed))
    except ValueError:
        return peer


def limit_by_ip(*scopes: RateScope) -> Callable[[Request], None]:
    """Every scope is checked in order (e.g. a per-minute and a per-day window)."""

    def dependency(request: Request) -> None:
        for scope in scopes:
            enforce_rate_limit(request, scope, client_ip(request))

    return dependency


def limit_by_user(*scopes: RateScope) -> Callable[..., None]:
    def dependency(request: Request, user: CurrentUser) -> None:
        for scope in scopes:
            enforce_rate_limit(request, scope, str(user.id))

    return dependency


def limit_by_upload_user(*scopes: RateScope) -> Callable[..., None]:
    """Like ``limit_by_user`` but also accepts the upload-only token."""

    def dependency(request: Request, user: UploadUser) -> None:
        for scope in scopes:
            enforce_rate_limit(request, scope, str(user.id))

    return dependency
