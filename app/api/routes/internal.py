"""Internal endpoints for other containers of the stack (not public, not in the docs).

``POST /internal/embed`` lets the Celery worker use the API's embedding model
(EMBEDDING_PROVIDER=remote), so a small machine holds a single model copy. It is
enabled only when INTERNAL_EMBED_SECRET is set, requires that secret in the
``X-Internal-Secret`` header (constant-time comparison) and is blocked at Caddy.
The request body is capped by MAX_REQUEST_BODY_BYTES (BodySizeLimitMiddleware) and
the batch by INTERNAL_EMBED_MAX_BATCH / INTERNAL_EMBED_MAX_TEXT_CHARS.
"""

import hmac
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from app.ai.base import EmbeddingProvider
from app.ai.errors import AIProviderConfigurationError, EmbeddingError
from app.ai.remote_embeddings import SECRET_HEADER, RemoteEmbeddingProvider
from app.api.dependencies.services import get_embedder
from app.api.dependencies.settings import AppSettings
from app.core.errors import (
    AuthenticationError,
    InvalidQueryError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", include_in_schema=False)


class EmbedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texts: list[str] = Field(min_length=1)
    kind: Literal["passage", "query"] = "passage"


class EmbedResponse(BaseModel):
    model: str
    dimension: int
    vectors: list[list[float]]


def require_internal_secret(
    settings: AppSettings,
    secret: Annotated[str | None, Header(alias=SECRET_HEADER)] = None,
) -> None:
    expected = settings.internal_embed_secret
    if expected is None:
        raise NotFoundError()
    if not secret:
        raise AuthenticationError("Internal secret required")
    if not hmac.compare_digest(secret.encode("utf-8"), expected.get_secret_value().encode("utf-8")):
        raise PermissionDeniedError("Invalid internal secret")


@router.post("/embed", dependencies=[Depends(require_internal_secret)])
def embed(
    body: EmbedRequest,
    settings: AppSettings,
    embedder: Annotated[EmbeddingProvider | None, Depends(get_embedder)],
) -> EmbedResponse:
    if len(body.texts) > settings.internal_embed_max_batch:
        raise InvalidQueryError(f"At most {settings.internal_embed_max_batch} texts per request")
    if any(len(text) > settings.internal_embed_max_text_chars for text in body.texts):
        raise InvalidQueryError(
            f"Each text must be at most {settings.internal_embed_max_text_chars} characters"
        )
    if embedder is None or isinstance(embedder, RemoteEmbeddingProvider):
        # The API must hold the model itself; a remote API would call itself in a loop.
        raise ServiceUnavailableError("Embedding is not available in this process")
    try:
        if body.kind == "query":
            vectors = [embedder.embed_query(text) for text in body.texts]
        else:
            vectors = embedder.embed(body.texts)
    except (EmbeddingError, AIProviderConfigurationError, OSError) as exc:
        logger.warning("internal.embed_failed", extra={"error_type": type(exc).__name__})
        raise ServiceUnavailableError("Embedding failed") from exc
    return EmbedResponse(model=embedder.model_name, dimension=embedder.dimension, vectors=vectors)
