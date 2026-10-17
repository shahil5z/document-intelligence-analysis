from typing import Annotated

from fastapi import Depends

from app.api.dependencies.auth import Hasher
from app.api.dependencies.db import DbSession
from app.api.dependencies.settings import AppSettings
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.services.task_dispatcher import DocumentTaskDispatcher
from app.services.user_service import UserService
from app.storage.base import StorageService
from app.storage.factory import get_storage_service
from app.workers.dispatcher import CeleryDocumentTaskDispatcher


def get_task_dispatcher() -> DocumentTaskDispatcher:
    # Tests override this dependency with a recording fake, so they need no broker.
    return CeleryDocumentTaskDispatcher()


def get_storage() -> StorageService:
    return get_storage_service()


def get_auth_service(session: DbSession, hasher: Hasher, settings: AppSettings) -> AuthService:
    return AuthService(session, hasher, settings)


def get_document_service(
    session: DbSession,
    storage: Annotated[StorageService, Depends(get_storage)],
    dispatcher: Annotated[DocumentTaskDispatcher, Depends(get_task_dispatcher)],
    settings: AppSettings,
) -> DocumentService:
    return DocumentService(session, storage, dispatcher, settings)


def get_audit_service(session: DbSession) -> AuditService:
    return AuditService(session)


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
