class AIProviderConfigurationError(RuntimeError):
    """Raised when an AI provider is requested but not configured (e.g. no API key)."""


class EmbeddingError(RuntimeError):
    """Embedding failed at runtime (model could not be loaded or inference failed)."""


class LLMError(RuntimeError):
    """The language model call failed (timeout, HTTP error, malformed response).

    Messages are generic; they never include the API key, prompts or response bodies.
    """


class EmbeddingServiceUnavailableError(OSError):
    """The remote embedding service (the API's /internal/embed) could not be reached.

    An ``OSError`` on purpose: the worker treats it as transient (the job is retried) and
    search answers 503, exactly like other connectivity failures.
    """
