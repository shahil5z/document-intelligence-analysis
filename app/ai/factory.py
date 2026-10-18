"""Factories that build AI providers from settings on demand.

The OpenAI SDK is imported and the client constructed only when a provider is
requested, so the API, worker and tests start without an API key and without network.
"""

from typing import TYPE_CHECKING

from app.ai.base import EmbeddingProvider, LLMProvider
from app.ai.errors import AIProviderConfigurationError
from app.ai.openai_provider import OpenAIChatProvider, OpenAIEmbeddingProvider
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
