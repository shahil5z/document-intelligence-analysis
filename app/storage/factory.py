from functools import lru_cache

from app.core.config import Settings, get_settings
from app.storage.base import StorageConfigurationError, StorageService
from app.storage.local import LocalStorage

SUPPORTED_BACKENDS = ("local",)


def check_storage_backend(settings: Settings) -> None:
    """Fail fast (API and worker startup) if ``STORAGE_BACKEND`` names no known backend."""
    if settings.storage_backend not in SUPPORTED_BACKENDS:
        raise StorageConfigurationError(
            f"Unsupported STORAGE_BACKEND {settings.storage_backend!r}; "
            f"supported: {', '.join(SUPPORTED_BACKENDS)}"
        )


def build_storage_service(settings: Settings) -> StorageService:
    """Create the backend named by ``STORAGE_BACKEND``; unknown names fail loudly."""
    check_storage_backend(settings)
    return LocalStorage(settings.storage_path)


@lru_cache
def get_storage_service() -> StorageService:
    """Process-wide storage backend chosen from settings."""
    return build_storage_service(get_settings())
