"""Shared OpenAPI response declarations so every documented error uses ErrorResponse."""

from typing import Any

from app.schemas.common import ErrorResponse

_DESCRIPTIONS = {
    400: "Bad request",
    401: "Missing, invalid or expired access token / credentials",
    403: "Authenticated but not allowed",
    404: "Resource not found (or not owned by the caller)",
    409: "Conflict with existing data",
    413: "Uploaded file too large",
    415: "Unsupported file type",
    422: "Request validation failed",
    429: "Rate limit exceeded (see the Retry-After header)",
    503: "A dependency is unavailable",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"model": ErrorResponse, "description": _DESCRIPTIONS.get(code, "Error")}
        for code in status_codes
    }
