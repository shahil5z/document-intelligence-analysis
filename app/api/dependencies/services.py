from typing import Annotated

from fastapi import Depends

from app.ai.base import EmbeddingProvider, LLMProvider, Reranker
from app.ai.errors import AIProviderConfigurationError
from app.ai.factory import create_embedding_provider, create_llm_provider, create_reranker
from app.api.dependencies.auth import Hasher
from app.api.dependencies.db import DbSession
from app.api.dependencies.settings import AppSettings
from app.processing.chunking import ApproximateTokenCounter, TokenCounter
from app.services.answer_service import AnswerService
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.services.search_service import SearchService
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


# --- DIP2: retrieval and question answering --------------------------------------------


def get_embedder(settings: AppSettings) -> EmbeddingProvider | None:
    """Process-wide embedding provider (weights load on first query). Tests override it."""
    try:
        return create_embedding_provider(settings)
    except AIProviderConfigurationError:
        return None


def get_reranker(settings: AppSettings) -> Reranker | None:
    return create_reranker(settings)


def get_llm(settings: AppSettings) -> LLMProvider | None:
    """``None`` when no LLM is configured: /ask then answers 503 (after retrieval)."""
    try:
        return create_llm_provider(settings)
    except AIProviderConfigurationError:
        return None


def get_context_token_counter() -> TokenCounter:
    return ApproximateTokenCounter()


def get_search_service(
    session: DbSession,
    settings: AppSettings,
    embedder: Annotated[EmbeddingProvider | None, Depends(get_embedder)],
    reranker: Annotated[Reranker | None, Depends(get_reranker)],
) -> SearchService:
    return SearchService(session, settings, embedder, reranker)


def get_answer_service(
    search: Annotated[SearchService, Depends(get_search_service)],
    settings: AppSettings,
    llm: Annotated[LLMProvider | None, Depends(get_llm)],
    counter: Annotated[TokenCounter, Depends(get_context_token_counter)],
) -> AnswerService:
    return AnswerService(search, settings, llm, counter)


SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
AnswerServiceDep = Annotated[AnswerService, Depends(get_answer_service)]
