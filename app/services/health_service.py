import logging

import redis
from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.db.repositories.chunks import (
    ITERATIVE_SCAN_MIN_VERSION,
    PGVECTOR_MIN_VERSION,
    parse_extension_version,
)
from app.db.session import get_engine
from app.schemas.health import DependencyCheck

logger = logging.getLogger(__name__)

_CHECK_TIMEOUT_SECONDS = 2.0
_PGVECTOR_QUERY = text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")


def _version_text(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def evaluate_pgvector_version(version: str | None) -> DependencyCheck:
    """``ok`` for pgvector >= 0.5.0; a fixed, value-free error otherwise."""
    parsed = parse_extension_version(version)
    if not parsed:
        return DependencyCheck(status="error", error="pgvector extension is not installed")
    if parsed < PGVECTOR_MIN_VERSION:
        return DependencyCheck(
            status="error",
            error=f"pgvector >= {_version_text(PGVECTOR_MIN_VERSION)} is required",
        )
    if parsed < ITERATIVE_SCAN_MIN_VERSION:
        logger.warning(
            "health.pgvector_without_iterative_scan",
            extra={"recommended": _version_text(ITERATIVE_SCAN_MIN_VERSION)},
        )
    return DependencyCheck(status="ok")


class HealthService:
    def __init__(self, engine: Engine, redis_url: str) -> None:
        self._engine = engine
        self._redis_url = redis_url

    def check_database(self) -> DependencyCheck:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("health.database_unavailable", extra={"exc_type": type(exc).__name__})
            return DependencyCheck(status="error", error="database unavailable")
        return DependencyCheck(status="ok")

    def check_pgvector(self) -> DependencyCheck:
        try:
            with self._engine.connect() as connection:
                version = connection.execute(_PGVECTOR_QUERY).scalar()
        except Exception as exc:
            logger.warning("health.pgvector_check_failed", extra={"exc_type": type(exc).__name__})
            return DependencyCheck(status="error", error="database unavailable")
        return evaluate_pgvector_version(None if version is None else str(version))

    def check_redis(self) -> DependencyCheck:
        client = redis.Redis.from_url(
            self._redis_url,
            socket_connect_timeout=_CHECK_TIMEOUT_SECONDS,
            socket_timeout=_CHECK_TIMEOUT_SECONDS,
        )
        try:
            client.ping()
        except Exception as exc:
            logger.warning("health.redis_unavailable", extra={"exc_type": type(exc).__name__})
            return DependencyCheck(status="error", error="redis unavailable")
        finally:
            client.close()
        return DependencyCheck(status="ok")


def get_health_service() -> HealthService:
    return HealthService(get_engine(), get_settings().get_redis_url())
