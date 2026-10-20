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
from app.ai.onnx_embeddings import OnnxEmbeddingProvider, TokenizerCounter
from app.ai.openai_provider import OpenAIChatProvider, OpenAIEmbeddingProvider
from app.ai.remote_embeddings import RemoteEmbeddingProvider
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
def _cached_embedding_provider(  # noqa: PLR0917  (lru_cache key = settings tuple)
    model: str,
    dimension: int,
    batch_size: int,
    device: str,
    query_instruction: str,
    num_threads: int = 0,
) -> SentenceTransformerEmbeddingProvider:
    return SentenceTransformerEmbeddingProvider(
        model,
        expected_dimension=dimension,
        batch_size=batch_size,
        device=device,
        query_instruction=query_instruction,
        num_threads=num_threads,
    )


@lru_cache
def _cached_onnx_provider(  # noqa: PLR0917  (lru_cache key = settings tuple)
    model: str,
    dimension: int,
    onnx_file: str,
    batch_size: int,
    query_instruction: str,
    num_threads: int = 0,
) -> OnnxEmbeddingProvider:
    return OnnxEmbeddingProvider(
        model,
        expected_dimension=dimension,
        onnx_file=onnx_file,
        batch_size=batch_size,
        query_instruction=query_instruction,
        num_threads=num_threads,
    )


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Process-wide provider for EMBEDDING_PROVIDER (model weights load on first use)."""
    if settings.embedding_provider == "onnx":
        return _cached_onnx_provider(
            settings.embedding_model,
            settings.embedding_dimension,
            settings.embedding_onnx_file,
            settings.embedding_batch_size,
            settings.embedding_query_instruction,
            settings.torch_num_threads,
        )
    if settings.embedding_provider == "remote":
        if settings.embedding_remote_url is None or settings.internal_embed_secret is None:
            raise AIProviderConfigurationError(
                "EMBEDDING_PROVIDER=remote needs EMBEDDING_REMOTE_URL and INTERNAL_EMBED_SECRET"
            )
        # Stateless HTTP client: no model and no cache needed.
        return RemoteEmbeddingProvider(
            settings.embedding_remote_url,
            settings.internal_embed_secret.get_secret_value(),
            model_name=settings.embedding_model,
            expected_dimension=settings.embedding_dimension,
            batch_size=min(settings.embedding_batch_size, settings.internal_embed_max_batch),
            timeout_seconds=settings.embedding_remote_timeout_seconds,
        )
    if settings.embedding_provider == "sentence-transformers":
        return _cached_embedding_provider(
            settings.embedding_model,
            settings.embedding_dimension,
            settings.embedding_batch_size,
            settings.embedding_device,
            settings.embedding_query_instruction,
            settings.torch_num_threads,
        )
    raise AIProviderConfigurationError("Unsupported EMBEDDING_PROVIDER")


@lru_cache
def _cached_token_counter(model: str) -> TokenizerCounter:
    return TokenizerCounter(model)


def create_token_counter(settings: Settings) -> TokenizerCounter:
    """Chunking token counter: the embedding model's tokenizer only (no model weights)."""
    return _cached_token_counter(settings.embedding_model)


@lru_cache
def _cached_reranker(model: str, device: str, num_threads: int = 0) -> CrossEncoderReranker:
    return CrossEncoderReranker(model, device=device, num_threads=num_threads)


def create_reranker(settings: Settings) -> Reranker | None:
    if not settings.reranking_enabled:
        return None
    return _cached_reranker(
        settings.reranker_model, settings.embedding_device, settings.torch_num_threads
    )


@lru_cache(maxsize=4)
def _cached_llm_provider(
    *,
    api_key: str,
    model: str,
    base_url: str,
    timeout_seconds: float,
    max_output_tokens: int,
    temperature: float,
    structured_output: bool = True,
) -> OpenAICompatibleLLMProvider:
    # One HTTP client (connection pool) per process and configuration, instead of a new,
    # never-closed client per /ask request.
    return OpenAICompatibleLLMProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        structured_output=structured_output,
    )


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Build the /ask LLM client. Raises ``AIProviderConfigurationError`` if unusable."""
    if settings.llm_provider == "none":
        raise AIProviderConfigurationError("LLM_PROVIDER is 'none'; question answering is off")
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not key.strip() or key.lower().startswith(_PLACEHOLDER_PREFIX):
        raise AIProviderConfigurationError(
            "OPENAI_API_KEY is not configured; set it in .env to use AI features"
        )
    return _cached_llm_provider(
        api_key=key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        temperature=settings.llm_temperature,
        structured_output=settings.llm_structured_output,
    )
