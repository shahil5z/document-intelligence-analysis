class AIProviderConfigurationError(RuntimeError):
    """Raised when an AI provider is requested but not configured (e.g. no API key)."""
