"""Pure ASGI middleware: request ids, access logging, and last-resort error handling."""

import logging
import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import unhandled_error_response
from app.core.request_context import (
    REQUEST_ID_HEADER,
    RequestContext,
    bind_context,
    reset_context,
    sanitize_request_id,
)

logger = logging.getLogger("app.request")


class RequestContextMiddleware:
    """Assigns a request id, echoes it as ``X-Request-ID``, and logs one line per request.

    An incoming ``X-Request-ID`` is reused only if it matches ``[A-Za-z0-9-]{8,64}``
    (UUIDs qualify); anything else is replaced by a fresh UUID4 so clients cannot inject
    arbitrary content into logs. Unhandled exceptions are logged with a stack trace and
    converted into the generic 500 error envelope (no internals leak to the client).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

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
            logger.info(
                "request.completed",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            reset_context(token)
