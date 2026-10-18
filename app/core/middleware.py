"""Pure ASGI middleware: request ids, access logging, metrics, body limits, headers.

Order (outermost first, see ``app.main._register_middleware``)::

    RequestContextMiddleware -> SecurityHeadersMiddleware -> BodySizeLimitMiddleware
    -> CORSMiddleware -> routes

so every response, including 413/500 envelopes and CORS preflights, carries a request
id, security headers and is counted in the metrics.
"""

import contextlib
import logging
import time
from collections.abc import Iterable

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import payload_too_large_response, unhandled_error_response
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS, UNMATCHED_ROUTE, status_label
from app.core.request_context import (
    REQUEST_ID_HEADER,
    RequestContext,
    bind_context,
    reset_context,
    sanitize_request_id,
)

logger = logging.getLogger("app.request")


def route_template(scope: Scope) -> str:
    """The matched route's path template (low cardinality), or ``unmatched``."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else UNMATCHED_ROUTE


class RequestContextMiddleware:
    """Assigns a request id, echoes it as ``X-Request-ID``, logs and measures each request.

    An incoming ``X-Request-ID`` is reused only if it matches ``[A-Za-z0-9-]{8,64}``
    (UUIDs qualify); anything else is replaced by a fresh UUID4 so clients cannot inject
    arbitrary content into logs. Unhandled exceptions are logged with a stack trace and
    converted into the generic 500 error envelope (no internals leak to the client).
    Metrics use the route template, never the raw path, so ids do not explode label sets.
    """

    def __init__(self, app: ASGIApp, *, metrics_enabled: bool = True) -> None:
        self.app = app
        self.metrics_enabled = metrics_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming: str | None = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        context = RequestContext(request_id=sanitize_request_id(incoming))
        token = bind_context(context)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = context.request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("request.unhandled_error")
            if not response_started:
                response = unhandled_error_response()
                await response(scope, receive, send)
            status_code = 500
        finally:
            duration = time.perf_counter() - started
            method = str(scope.get("method", ""))
            route = route_template(scope)
            if self.metrics_enabled:
                HTTP_REQUESTS.labels(method, route, status_label(status_code)).inc()
                HTTP_LATENCY.labels(method, route).observe(duration)
            logger.info(
                "request.completed",
                extra={
                    "method": method,
                    "path": scope.get("path"),
                    "route": route,
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            reset_context(token)


class _BodyTooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject request bodies above a limit *before* they are fully read or spooled.

    ``Content-Length`` above the limit is rejected immediately. Bodies without a length
    (chunked) are counted while the application reads them; once the limit is passed,
    reading stops and the application's response is replaced by the 413 envelope.
    Upload routes (``POST`` to a path in ``upload_paths``) get ``upload_limit``.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_limit: int,
        upload_limit: int,
        upload_paths: Iterable[str] = ("/documents",),
    ) -> None:
        self.app = app
        self.default_limit = default_limit
        self.upload_limit = upload_limit
        self.upload_paths = frozenset(path.rstrip("/") for path in upload_paths)

    def _limit_for(self, scope: Scope) -> int:
        path = str(scope.get("path", "")).rstrip("/")
        if scope.get("method") == "POST" and path in self.upload_paths:
            return self.upload_limit
        return self.default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit_for(scope)
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared > limit:
                    await payload_too_large_response(limit)(scope, receive, send)
                    return
                break

        received = 0
        exceeded = False
        replaced = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal replaced
            if exceeded:
                # Drop whatever the app produced (typically a 400 parse error) once.
                if not replaced and message["type"] == "http.response.start":
                    replaced = True
                    await payload_too_large_response(limit)(scope, receive, send)
                return
            await send(message)

        with contextlib.suppress(_BodyTooLargeError):
            await self.app(scope, limited_receive, guarded_send)
        if exceeded and not replaced:
            await payload_too_large_response(limit)(scope, receive, send)


_BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}
_HSTS = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    """Conservative headers for a JSON API; HSTS only when served in production."""

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.headers = dict(_BASE_SECURITY_HEADERS)
        if hsts:
            self.headers["Strict-Transport-Security"] = _HSTS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
