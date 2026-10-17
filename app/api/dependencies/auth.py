from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.api.dependencies.db import DbSession
from app.api.dependencies.settings import AppSettings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.request_context import set_user_id
from app.core.security import InvalidTokenError, PasswordHasher, decode_access_token
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.domain.enums import UserRole

# tokenUrl points at the OAuth2 form endpoint so Swagger UI's "Authorize" button works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


@lru_cache
def get_password_hasher() -> PasswordHasher:
    return PasswordHasher()


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: DbSession,
    settings: AppSettings,
) -> User:
    if not token:
        raise AuthenticationError("Not authenticated")
    try:
        payload = decode_access_token(token, settings)
    except InvalidTokenError as exc:
        raise AuthenticationError("Could not validate credentials") from exc
    # Role and active flag are read from the database, not trusted from the token,
    # so demotions and deactivations take effect immediately.
    user = UserRepository(session).get(payload.subject)
    if user is None:
        raise AuthenticationError("Could not validate credentials")
    set_user_id(str(user.id))
    return user


def get_current_active_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_active:
        raise PermissionDeniedError("This account is disabled")
    return user


def require_admin(user: Annotated[User, Depends(get_current_active_user)]) -> User:
    if user.role is not UserRole.ADMIN:
        raise PermissionDeniedError("Administrator privileges required")
    return user


CurrentUser = Annotated[User, Depends(get_current_active_user)]
AdminUser = Annotated[User, Depends(require_admin)]
Hasher = Annotated[PasswordHasher, Depends(get_password_hasher)]
