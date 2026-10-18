from pathlib import Path

import pytest

from app.core.config import load_settings
from app.main import create_app
from app.storage.base import StorageConfigurationError
from app.storage.factory import build_storage_service
from app.storage.local import LocalStorage


def test_local_backend_is_built(tmp_path: Path) -> None:
    settings = load_settings(
        _env_file=None, app_env="test", jwt_secret_key="k" * 40, storage_path=tmp_path
    )
    assert isinstance(build_storage_service(settings), LocalStorage)


def test_unknown_backend_is_rejected_clearly(tmp_path: Path) -> None:
    settings = load_settings(
        _env_file=None,
        app_env="test",
        jwt_secret_key="k" * 40,
        storage_backend="S3",
        storage_path=tmp_path,
    )
    with pytest.raises(StorageConfigurationError, match="Unsupported STORAGE_BACKEND 's3'"):
        build_storage_service(settings)


def test_app_refuses_to_start_with_unknown_backend(tmp_path: Path) -> None:
    settings = load_settings(
        _env_file=None, app_env="test", jwt_secret_key="k" * 40, storage_backend="ftp"
    )
    with pytest.raises(StorageConfigurationError, match="STORAGE_BACKEND"):
        create_app(settings)
