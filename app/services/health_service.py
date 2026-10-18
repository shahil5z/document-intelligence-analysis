import logging

import redis
from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.db.session import get_engine
from app.schemas.health import DependencyCheck

logger = logging.getLogger(__name__)

_CHECK_TIMEOUT_SECONDS = 2.0


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
