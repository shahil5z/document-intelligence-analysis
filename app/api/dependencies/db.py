from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_session_factory


def get_db_session() -> Iterator[Session]:
    """One session per request.

    Services commit explicitly at their transaction boundaries. Anything left
    uncommitted when the request ends (including after an exception) is rolled back,
    and the session is always closed and its connection returned to the pool.
    """
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# scope="function": tear down before the response is sent, so connections are released
# promptly and nothing touches the session after the route returns.
DbSession = Annotated[Session, Depends(get_db_session, scope="function")]
