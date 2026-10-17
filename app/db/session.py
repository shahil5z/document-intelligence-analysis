"""Engine and session factory (synchronous SQLAlchemy 2.x, psycopg 3 driver).

Engines are created lazily and cached per process; Celery worker processes and API
processes therefore each own their connection pool. See docs/adr/ADR-005.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={"connect_timeout": 5},
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    """Session for non-request code (workers, scripts).

    Callers commit explicitly; any exception triggers a rollback and the session is
    always closed.
    """
    session = (factory or get_session_factory())()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
