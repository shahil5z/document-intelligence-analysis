"""Structured JSON logging with request context and secret redaction."""

import json
import logging
import logging.config
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import get_context

_SENSITIVE_KEY_PARTS = ("password", "token", "secret", "authorization", "cookie", "jwt")
_REDACTED = "[REDACTED]"
_RESERVED_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys() | {"message", "asctime"}
)


def _redact(value: Any, key: str | None = None) -> Any:
    if key is not None and any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return _REDACTED
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """Render each record as one JSON object per line.

    Extra fields passed via ``logger.info("event", extra={...})`` are included after
    redaction of keys that look sensitive (password, token, secret, ...).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        context = get_context()
        if context is not None:
            payload["request_id"] = context.request_id
            if context.user_id:
                payload["user_id"] = context.user_id
            if context.document_id:
                payload["document_id"] = context.document_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = _redact(value, key)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Configure root, uvicorn and celery loggers to emit JSON to stdout."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"level": level, "handlers": ["stdout"]},
            "loggers": {
                "uvicorn": {"level": level, "handlers": ["stdout"], "propagate": False},
                "uvicorn.error": {"level": level, "handlers": ["stdout"], "propagate": False},
                # Request logging is done by our middleware (with request ids), so silence
                # uvicorn's own access log to avoid duplicate, context-free lines.
                "uvicorn.access": {"level": "WARNING", "handlers": ["stdout"], "propagate": False},
                "celery": {"level": level, "handlers": ["stdout"], "propagate": False},
                "sqlalchemy.engine": {"level": "WARNING"},
            },
        }
    )
