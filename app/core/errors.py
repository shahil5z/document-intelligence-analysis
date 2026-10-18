"""Application error types and the consistent JSON error envelope.

Every error response has the shape::

    {"error": {"code": "...", "message": "...", "request_id": "...", "details": [...]}}
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import REQUEST_ID_HEADER, get_request_id

logger = logging.getLogger(__name__)

_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


class AppError(Exception):
    """Base class for expected, client-facing errors raised by services."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "Bad request"

    def __init__(self, message: str | None = None, *, headers: dict[str, str] | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.headers = headers


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"
    message = "Could not validate credentials"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "You do not have permission to perform this action"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource already exists"


class PayloadTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "payload_too_large"
    message = "Uploaded file exceeds the maximum allowed size"


class UnsupportedMediaTypeError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_media_type"
    message = "Unsupported file type"


class InvalidUploadError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_upload"
    message = "Invalid upload"


class InvalidQueryError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"
    message = "Invalid query"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests; retry later"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(headers={"Retry-After": str(max(1, retry_after_seconds))})


DemoLimit = Literal["questions", "uploads", "file_size", "file_type", "disabled", "expired"]


class DemoLimitReachedError(AppError):
    """A demo account hit one of its limits; the client offers a free account instead."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "demo_limit_reached"
    message = "Demo limit reached. Create a free account to continue."

    def __init__(self, limit: DemoLimit, message: str | None = None) -> None:
        super().__init__(message)
        self.limit = limit
        self.details: list[dict[str, Any]] = [{"limit": limit}]


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "Service temporarily unavailable"


def error_body(
    code: str, message: str, details: Sequence[dict[str, Any]] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": get_request_id()}
    if details:
        body["details"] = list(details)
    return {"error": body}


def _response(
    status_code: int,
    code: str,
    message: str,
    details: Sequence[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    request_id = get_request_id()
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, message, details),
        headers=response_headers,
    )


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(AppError, exc)
    details: Sequence[dict[str, Any]] | None = getattr(exc, "details", None)
    return _response(exc.status_code, exc.code, exc.message, details, headers=exc.headers)


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    code = _STATUS_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _response(exc.status_code, code, message, headers=exc.headers)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)
    # Deliberately drop the "input" and "ctx" members so submitted values
    # (which may include passwords) are never echoed back.
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        "Request validation failed",
        details=details,
    )


def payload_too_large_response(limit: int) -> JSONResponse:
    """413 sent by the body-size middleware before (or instead of) the route's response."""
    return _response(
        status.HTTP_413_CONTENT_TOO_LARGE,
        "payload_too_large",
        f"Request body exceeds the maximum allowed size of {limit} bytes",
    )


def unhandled_error_response() -> JSONResponse:
    """Generic 500 used by the request-id middleware; never includes exception details."""
    return _response(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "Internal server error"
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
