from functools import lru_cache

from app.core.config import Settings, get_settings
from app.storage.base import StorageConfigurationError, StorageService
from app.storage.local import LocalStorage

SUPPORTED_BACKENDS = ("local", "s3", "oci")


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
    if settings.storage_backend in {"s3", "oci"}:
        from app.storage.s3 import S3Storage  # noqa: PLC0415  (boto3 only when used)

        # Settings validation guarantees these are set for s3/oci.
        assert settings.storage_s3_bucket is not None  # noqa: S101
        assert settings.storage_s3_access_key_id is not None  # noqa: S101
        assert settings.storage_s3_secret_access_key is not None  # noqa: S101
        return S3Storage(
            bucket=settings.storage_s3_bucket,
            access_key_id=settings.storage_s3_access_key_id.get_secret_value(),
            secret_access_key=settings.storage_s3_secret_access_key.get_secret_value(),
            endpoint_url=settings.storage_s3_endpoint_url,
            region=settings.storage_s3_region,
            prefix=settings.storage_s3_prefix,
            addressing_style=settings.storage_s3_addressing_style,
        )
    return LocalStorage(settings.storage_path)


@lru_cache
def get_storage_service() -> StorageService:
    """Process-wide storage backend chosen from settings."""
    return build_storage_service(get_settings())
