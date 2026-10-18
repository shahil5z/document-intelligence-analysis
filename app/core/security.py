"""Password hashing (Argon2id via pwdlib) and JWT access tokens (PyJWT)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import Settings
from app.domain.enums import UserRole

ACCESS_TOKEN_TYPE = "access"  # noqa: S105  (JWT "type" claim, not a secret)


class PasswordHasher:
    """Thin wrapper so the hashing algorithm can be swapped in one place."""

    def __init__(self) -> None:
        self._hasher = PasswordHash((Argon2Hasher(),))
        # Used to keep login timing similar for unknown e-mail addresses.
        self._dummy_hash = self._hasher.hash(uuid.uuid4().hex)

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        return self._hasher.verify(password, password_hash)

    def verify_dummy(self, password: str) -> None:
        self._hasher.verify(password, self._dummy_hash)


@dataclass(frozen=True)
class TokenPayload:
    subject: uuid.UUID
    role: UserRole
    token_id: str
    issued_at: datetime
    expires_at: datetime


class InvalidTokenError(Exception):
    """Raised when a token is malformed, expired, or has unexpected claims."""


def create_access_token(
    *, user_id: uuid.UUID, role: UserRole, settings: Settings, now: datetime | None = None
) -> tuple[str, int]:
    """Return ``(encoded_token, expires_in_seconds)``."""
    issued_at = now or datetime.now(UTC)
    lifetime = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    claims = {
        "sub": str(user_id),
        "role": role.value,
        "type": ACCESS_TOKEN_TYPE,
        "jti": uuid.uuid4().hex,
        "iss": settings.jwt_issuer,
        "iat": issued_at,
        "exp": issued_at + lifetime,
    }
    token = jwt.encode(
        claims, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> TokenPayload:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "role", "type", "jti", "iat", "exp", "iss"]},
        )
        if claims["type"] != ACCESS_TOKEN_TYPE:
            raise InvalidTokenError("unexpected token type")
        return TokenPayload(
            subject=uuid.UUID(str(claims["sub"])),
            role=UserRole(claims["role"]),
            token_id=str(claims["jti"]),
            issued_at=datetime.fromtimestamp(int(claims["iat"]), tz=UTC),
            expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError(str(exc)) from exc
