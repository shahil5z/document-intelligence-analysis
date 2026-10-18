class AIProviderConfigurationError(RuntimeError):
    """Raised when an AI provider is requested but not configured (e.g. no API key)."""


class EmbeddingError(RuntimeError):
    """Embedding failed at runtime (model could not be loaded or inference failed)."""


class LLMError(RuntimeError):
    """The language model call failed (timeout, HTTP error, malformed response).

    Messages are generic; they never include the API key, prompts or response bodies.
    """
