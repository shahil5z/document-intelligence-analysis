from typing import Annotated

from fastapi import Depends

from app.api.dependencies.auth import Hasher
from app.api.dependencies.db import DbSession
from app.api.dependencies.settings import AppSettings
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.user_service import UserService


def get_auth_service(session: DbSession, hasher: Hasher, settings: AppSettings) -> AuthService:
    return AuthService(session, hasher, settings)


def get_audit_service(session: DbSession) -> AuditService:
    return AuditService(session)


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
