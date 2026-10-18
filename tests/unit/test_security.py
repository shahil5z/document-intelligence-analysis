import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    PasswordHasher,
    create_access_token,
    decode_access_token,
)
from app.domain.enums import UserRole


def test_password_hash_roundtrip_and_salting() -> None:
    hasher = PasswordHasher()
    first = hasher.hash("correct horse battery staple")
    second = hasher.hash("correct horse battery staple")
    assert first != second
    assert first.startswith("$argon2id$")
    assert hasher.verify("correct horse battery staple", first)
    assert not hasher.verify("wrong password", first)


def test_access_token_roundtrip_contains_expected_claims() -> None:
    settings = get_settings()
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id=user_id, role=UserRole.ADMIN, settings=settings)
    payload = decode_access_token(token, settings)
    assert payload.subject == user_id
    assert payload.role is UserRole.ADMIN
    assert expires_in == settings.jwt_access_token_expire_minutes * 60
    raw = jwt.decode(token, options={"verify_signature": False})
    assert {"sub", "role", "type", "jti", "iss", "iat", "exp"} <= raw.keys()


def test_expired_token_is_rejected() -> None:
    settings = get_settings()
    issued = datetime.now(UTC) - timedelta(days=1)
    token, _ = create_access_token(
        user_id=uuid.uuid4(), role=UserRole.USER, settings=settings, now=issued
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, settings)


def test_token_signed_with_other_secret_is_rejected() -> None:
    settings = get_settings()
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "admin",
            "type": "access",
            "jti": "x",
            "iss": settings.jwt_issuer,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "another-secret-that-is-at-least-32-chars-long",
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, settings)


def test_non_access_token_type_is_rejected() -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "user",
            "type": "refresh",
            "jti": "x",
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, settings)
