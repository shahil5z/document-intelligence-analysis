import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
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

    # --- demo accounts --------------------------------------------------------------

    def add_demo(self, *, email: str, password_hash: str, expires_at: datetime) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            role=UserRole.USER,
            is_active=True,
            is_demo=True,
            demo_expires_at=expires_at,
        )
        self._session.add(user)
        self._session.flush()
        return user

    def reserve_demo_question(self, user_id: uuid.UUID, limit: int) -> int | None:
        """Atomically count one question; the new count, or ``None`` at the limit."""
        used: int | None = self._session.scalar(
            update(User)
            .where(User.id == user_id, User.is_demo, User.demo_questions_used < limit)
            .values(demo_questions_used=User.demo_questions_used + 1)
            .returning(User.demo_questions_used)
        )
        return used

    def release_demo_question(self, user_id: uuid.UUID) -> None:
        self._session.execute(
            update(User)
            .where(User.id == user_id, User.is_demo, User.demo_questions_used > 0)
            .values(demo_questions_used=User.demo_questions_used - 1)
        )

    def reserve_demo_upload(self, user_id: uuid.UUID, limit: int) -> int | None:
        used: int | None = self._session.scalar(
            update(User)
            .where(User.id == user_id, User.is_demo, User.demo_uploads_used < limit)
            .values(demo_uploads_used=User.demo_uploads_used + 1)
            .returning(User.demo_uploads_used)
        )
        return used

    def release_demo_upload(self, user_id: uuid.UUID) -> None:
        self._session.execute(
            update(User)
            .where(User.id == user_id, User.is_demo, User.demo_uploads_used > 0)
            .values(demo_uploads_used=User.demo_uploads_used - 1)
        )

    def expired_demo_ids(self, now: datetime, limit: int) -> Sequence[uuid.UUID]:
        return self._session.scalars(
            select(User.id)
            .where(User.is_demo, User.demo_expires_at <= now)
            .order_by(User.demo_expires_at)
            .limit(limit)
        ).all()
