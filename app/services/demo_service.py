"""Demo mode: ephemeral, isolated accounts with hard server-side limits.

* ``POST /auth/demo`` creates a user with ``is_demo=True``, a random unusable password
  (password login is refused for demo users anyway) and ``demo_expires_at``.
* Limits (DEMO_MAX_QUESTIONS, DEMO_MAX_UPLOADS, DEMO_MAX_UPLOAD_BYTES,
  DEMO_ALLOWED_EXTENSIONS) are counted on the user row with atomic
  ``UPDATE ... WHERE used < limit RETURNING`` statements, so parallel requests cannot
  exceed them. A question that never reached the LLM (insufficient evidence below the
  threshold, LLM unavailable, error) is given back; a failed upload too.
* ``POST /auth/demo/convert`` turns the demo into a normal account (email + password),
  keeping its documents.
* ``cleanup_expired_demo_users`` (beat task ``users.cleanup_expired_demos``) deletes
  expired demo users - documents, chunks and jobs cascade - and then their stored files.

Isolation needs nothing special: demo users are ordinary owners, and every document,
search and ask query is already filtered by owner id.
"""

import logging
import secrets
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    DemoLimitReachedError,
    PermissionDeniedError,
)
from app.core.metrics import DEMO_EVENTS
from app.core.security import PasswordHasher, create_access_token
from app.db.models import Document, User
from app.db.repositories.users import UserRepository
from app.domain.enums import AuditAction, ResourceType
from app.services.audit_service import AuditService
from app.services.auth_service import normalize_email
from app.storage.base import StorageService

logger = logging.getLogger(__name__)

DEMO_EMAIL_DOMAIN = "demo.invalid"  # RFC 2606: can never receive mail
DEMO_DISABLED_MESSAGE = "The demo is currently unavailable. Create a free account instead."
DEMO_QUESTIONS_MESSAGE = "You have used all demo questions. Create a free account to continue."
DEMO_UPLOADS_MESSAGE = "The demo allows one document. Create a free account to upload more."
DEMO_EXPIRED_MESSAGE = "This demo session has expired."
# A demo session token never outlives the account; capped so a leaked token is short-lived.
DEMO_SESSION_MAX = timedelta(hours=2)
CLEANUP_BATCH = 200


def demo_email() -> str:
    return f"demo-{secrets.token_hex(8)}@{DEMO_EMAIL_DOMAIN}"


def is_expired(user: User, now: datetime | None = None) -> bool:
    if not user.is_demo or user.demo_expires_at is None:
        return False
    return user.demo_expires_at <= (now or datetime.now(UTC))


@dataclass(frozen=True)
class DemoSession:
    user: User
    access_token: str
    expires_in: int


class DemoService:
    def __init__(
        self,
        session: Session,
        hasher: PasswordHasher,
        settings: Settings,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._audit = AuditService(session)
        self._hasher = hasher
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(UTC))

    # --- lifecycle --------------------------------------------------------------------

    def create(self) -> DemoSession:
        if not self._settings.demo_enabled:
            raise DemoLimitReachedError("disabled", DEMO_DISABLED_MESSAGE)
        now = self._clock()
        expires_at = now + timedelta(hours=self._settings.demo_ttl_hours)
        user = self._users.add_demo(
            email=demo_email(),
            # Never shown to anyone; password login is refused for demo users anyway.
            password_hash=self._hasher.hash(secrets.token_urlsafe(32)),
            expires_at=expires_at,
        )
        self._audit.record(
            AuditAction.DEMO_CREATED,
            user_id=user.id,
            resource_type=ResourceType.USER,
            resource_id=user.id,
        )
        self._session.commit()
        DEMO_EVENTS.labels("created").inc()
        logger.info("demo.created", extra={"subject_user_id": str(user.id)})
        lifetime = min(expires_at - now, DEMO_SESSION_MAX)
        token, expires_in = create_access_token(
            user_id=user.id, role=user.role, settings=self._settings, now=now, lifetime=lifetime
        )
        return DemoSession(user=user, access_token=token, expires_in=expires_in)

    def convert(self, user: User, *, email: str, password: str) -> User:
        """Turn a demo account into a regular one (keeps its documents)."""
        if not user.is_demo:
            raise PermissionDeniedError("Only demo accounts can be converted")
        email = normalize_email(email)
        if self._users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists")
        user.email = email
        user.password_hash = self._hasher.hash(password)
        user.is_demo = False
        user.demo_expires_at = None
        try:
            self._audit.record(
                AuditAction.DEMO_CONVERTED,
                user_id=user.id,
                resource_type=ResourceType.USER,
                resource_id=user.id,
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("An account with this email already exists") from exc
        DEMO_EVENTS.labels("converted").inc()
        logger.info("demo.converted", extra={"subject_user_id": str(user.id)})
        return user

    # --- limits -----------------------------------------------------------------------

    @contextmanager
    def question(self, user: User) -> Iterator["QuestionReservation"]:
        """Reserve one demo question for the duration of an /ask call.

        Regular users pass straight through. The reservation is released when the call
        raises, or when the caller marks it ``llm_called = False``.
        """
        reservation = QuestionReservation()
        if not user.is_demo:
            yield reservation
            return
        used = self._users.reserve_demo_question(user.id, self._settings.demo_max_questions)
        self._session.commit()
        if used is None:
            DEMO_EVENTS.labels("limit_questions").inc()
            raise DemoLimitReachedError("questions", DEMO_QUESTIONS_MESSAGE)
        reservation.used = used
        try:
            yield reservation
        except BaseException:
            self._release_question(user)
            raise
        if not reservation.llm_called:
            self._release_question(user)
            reservation.used = used - 1
        self._session.refresh(user)

    def _release_question(self, user: User) -> None:
        self._users.release_demo_question(user.id)
        self._session.commit()

    def remaining_questions(self, user: User) -> int | None:
        if not user.is_demo:
            return None
        return max(0, self._settings.demo_max_questions - user.demo_questions_used)


@dataclass
class QuestionReservation:
    used: int = 0
    llm_called: bool = True


def reserve_demo_upload(session: Session, user: User, settings: Settings) -> None:
    """Count one demo upload (commits). Raises ``DemoLimitReachedError`` at the limit."""
    used = UserRepository(session).reserve_demo_upload(user.id, settings.demo_max_uploads)
    session.commit()
    if used is None:
        DEMO_EVENTS.labels("limit_uploads").inc()
        raise DemoLimitReachedError("uploads", DEMO_UPLOADS_MESSAGE)


def release_demo_upload(session: Session, user: User) -> None:
    UserRepository(session).release_demo_upload(user.id)
    session.commit()


def reject_expired_demo(user: User) -> None:
    """Expired demo users are refused even before the cleanup task removed them."""
    if is_expired(user):
        raise AuthenticationError(DEMO_EXPIRED_MESSAGE)


def cleanup_expired_demo_users(
    session_factory: Callable[[], Session],
    storage: StorageService,
    *,
    now: datetime | None = None,
    batch: int = CLEANUP_BATCH,
) -> int:
    """Delete expired demo users and their files; returns the number of users deleted."""
    now = now or datetime.now(UTC)
    deleted = 0
    while True:
        with session_factory() as session:
            ids = UserRepository(session).expired_demo_ids(now, batch)
            if not ids:
                break
            for user_id in ids:
                deleted += _delete_demo_user(session, storage, user_id)
        if len(ids) < batch:
            break
    if deleted:
        DEMO_EVENTS.labels("expired_deleted").inc(deleted)
    logger.info("demo.cleanup", extra={"deleted": deleted})
    return deleted


def _delete_demo_user(session: Session, storage: StorageService, user_id: uuid.UUID) -> int:
    user = session.get(User, user_id)
    if user is None or not user.is_demo:
        return 0
    keys = list(session.scalars(select(Document.storage_key).where(Document.owner_id == user_id)))
    session.delete(user)  # documents, chunks and jobs cascade in the database
    session.commit()
    # Rows first: an orphaned file is recoverable, a row pointing at nothing is not.
    for key in keys:
        try:
            storage.delete(key)
        except Exception:
            logger.exception("demo.storage_delete_failed", extra={"subject_user_id": str(user_id)})
    return 1
