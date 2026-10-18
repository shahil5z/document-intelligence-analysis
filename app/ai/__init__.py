"""AI provider boundary for DIP2 (chat completion and embeddings).

Only interfaces and an OpenAI-backed factory exist in DIP1. Nothing here runs at
application startup, in health checks, or in the test suite's network path.
"""

from app.ai.base import ChatMessage, EmbeddingProvider, LLMProvider
from app.ai.errors import AIProviderConfigurationError
from app.ai.factory import get_embedding_provider, get_llm_provider

__all__ = [
    "AIProviderConfigurationError",
    "ChatMessage",
    "EmbeddingProvider",
    "LLMProvider",
    "get_embedding_provider",
    "get_llm_provider",
]
