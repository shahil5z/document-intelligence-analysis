import logging
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.security import PasswordHasher, create_access_token
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.domain.enums import AuditAction, ResourceType, UserRole
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS_MESSAGE = "Incorrect email or password"


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class IssuedToken:
    access_token: str
    expires_in: int


class AuthService:
    def __init__(self, session: Session, hasher: PasswordHasher, settings: Settings) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._audit = AuditService(session)
        self._hasher = hasher
        self._settings = settings

    def register(self, *, email: str, password: str) -> User:
        """Create a regular user. Self-registration can never create an admin."""
        email = normalize_email(email)
        if self._users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists")
        try:
            user = self._users.add(
                email=email, password_hash=self._hasher.hash(password), role=UserRole.USER
            )
            self._audit.record(
                AuditAction.USER_REGISTERED,
                user_id=user.id,
                resource_type=ResourceType.USER,
                resource_id=user.id,
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("An account with this email already exists") from exc
        logger.info("user.registered", extra={"subject_user_id": str(user.id)})
        return user

    def login(self, *, email: str, password: str) -> IssuedToken:
        user = self._users.get_by_email(normalize_email(email))
        if user is None:
            self._hasher.verify_dummy(password)
            self._record_failed_login(None, "invalid_credentials")
            raise AuthenticationError(INVALID_CREDENTIALS_MESSAGE)
        if not self._hasher.verify(password, user.password_hash):
            self._record_failed_login(user, "invalid_credentials")
            raise AuthenticationError(INVALID_CREDENTIALS_MESSAGE)
        if user.is_demo:
            # Demo accounts have no usable password; refuse like a wrong password.
            self._record_failed_login(user, "demo_account")
            raise AuthenticationError(INVALID_CREDENTIALS_MESSAGE)
        if not user.is_active:
            self._record_failed_login(user, "inactive_account")
            raise PermissionDeniedError("This account is disabled")

        self._audit.record(
            AuditAction.USER_LOGIN,
            user_id=user.id,
            resource_type=ResourceType.USER,
            resource_id=user.id,
        )
        self._session.commit()
        token, expires_in = create_access_token(
            user_id=user.id, role=user.role, settings=self._settings
        )
        logger.info("user.login", extra={"subject_user_id": str(user.id)})
        return IssuedToken(access_token=token, expires_in=expires_in)

    def _record_failed_login(self, user: User | None, reason: str) -> None:
        self._audit.record(
            AuditAction.USER_LOGIN_FAILED,
            user_id=user.id if user else None,
            resource_type=ResourceType.USER,
            resource_id=user.id if user else None,
            details={"reason": reason},
        )
        self._session.commit()
        logger.info("user.login_failed", extra={"reason": reason})
