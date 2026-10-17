import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import User
from app.domain.enums import UserRole


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self._session.scalar(select(User).where(User.email == email))

    def add(self, *, email: str, password_hash: str, role: UserRole = UserRole.USER) -> User:
        user = User(email=email, password_hash=password_hash, role=role, is_active=True)
        self._session.add(user)
        self._session.flush()
        return user

    def list(self, *, offset: int, limit: int) -> tuple[Sequence[User], int]:
        total = self._session.scalar(select(func.count()).select_from(User)) or 0
        rows = self._session.scalars(
            select(User).order_by(User.created_at.desc(), User.id).offset(offset).limit(limit)
        ).all()
        return rows, total
