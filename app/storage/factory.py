from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import StorageService
from app.storage.local import LocalStorage


@lru_cache
def get_storage_service() -> StorageService:
    """Process-wide storage backend chosen from settings (only local storage exists today)."""
    return LocalStorage(get_settings().storage_path)
