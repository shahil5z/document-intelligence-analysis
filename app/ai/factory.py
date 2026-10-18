"""Factories that build AI providers from settings on demand.

The OpenAI SDK is imported and the client constructed only when a provider is
requested, so the API, worker and tests start without an API key and without network.
"""

from functools import lru_cache
from typing import TYPE_CHECKING

from app.ai.base import EmbeddingProvider, LLMProvider, Reranker
from app.ai.embeddings import SentenceTransformerEmbeddingProvider
from app.ai.errors import AIProviderConfigurationError
from app.ai.llm import OpenAICompatibleLLMProvider
from app.ai.openai_provider import OpenAIChatProvider, OpenAIEmbeddingProvider
from app.ai.reranker import CrossEncoderReranker
from app.core.config import Settings

if TYPE_CHECKING:
    from openai import OpenAI

_PLACEHOLDER_PREFIX = "replace-with"


def build_openai_client(settings: Settings) -> "OpenAI":
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not key.strip() or key.lower().startswith(_PLACEHOLDER_PREFIX):
        raise AIProviderConfigurationError(
            "OPENAI_API_KEY is not configured; set it in .env to use AI features"
        )
    from openai import OpenAI  # noqa: PLC0415  (lazy: keep the SDK off the startup path)

    # api_key is passed explicitly so the SDK never falls back to other sources.
    return OpenAI(api_key=key, timeout=settings.openai_timeout_seconds, max_retries=2)


def get_llm_provider(settings: Settings) -> LLMProvider:
    return OpenAIChatProvider(build_openai_client(settings), settings.openai_chat_model)


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    return OpenAIEmbeddingProvider(build_openai_client(settings), settings.openai_embedding_model)


# --- DIP2 factories used by the worker pipeline, /search and /ask -----------------------


@lru_cache
def _cached_embedding_provider(
    model: str, dimension: int, batch_size: int, device: str, query_instruction: str
) -> SentenceTransformerEmbeddingProvider:
    return SentenceTransformerEmbeddingProvider(
        model,
        expected_dimension=dimension,
        batch_size=batch_size,
        device=device,
        query_instruction=query_instruction,
    )


def create_embedding_provider(settings: Settings) -> SentenceTransformerEmbeddingProvider:
    """Process-wide provider for EMBEDDING_PROVIDER (model weights load on first use)."""
    if settings.embedding_provider != "sentence-transformers":
        raise AIProviderConfigurationError("Unsupported EMBEDDING_PROVIDER")
    return _cached_embedding_provider(
        settings.embedding_model,
        settings.embedding_dimension,
        settings.embedding_batch_size,
        settings.embedding_device,
        settings.embedding_query_instruction,
    )


@lru_cache
def _cached_reranker(model: str, device: str) -> CrossEncoderReranker:
    return CrossEncoderReranker(model, device=device)


def create_reranker(settings: Settings) -> Reranker | None:
    if not settings.reranking_enabled:
        return None
    return _cached_reranker(settings.reranker_model, settings.embedding_device)


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Build the /ask LLM client. Raises ``AIProviderConfigurationError`` if unusable."""
    if settings.llm_provider == "none":
        raise AIProviderConfigurationError("LLM_PROVIDER is 'none'; question answering is off")
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not key.strip() or key.lower().startswith(_PLACEHOLDER_PREFIX):
        raise AIProviderConfigurationError(
            "OPENAI_API_KEY is not configured; set it in .env to use AI features"
        )
    return OpenAICompatibleLLMProvider(
        api_key=key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        temperature=settings.llm_temperature,
    )
