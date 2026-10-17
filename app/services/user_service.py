from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.db.models import User
from app.db.repositories.users import UserRepository


class UserService:
    def __init__(self, session: Session) -> None:
        self._users = UserRepository(session)

    def list_users(self, *, offset: int, limit: int) -> tuple[Sequence[User], int]:
        return self._users.list(offset=offset, limit=limit)
