"""APP_ENV=production rules: fail fast on unsafe settings, never echo values."""

from typing import Any

import pytest

from app.core.config import Settings, SettingsError, load_settings

SECRETS = {
    "jwt_secret_key": "j" * 48,
    "postgres_password": "pg-password-value-1234",
    "redis_password": "redis-password-value-1234",
}
SAFE = {
    "cors_allowed_origins": "https://app.example.com",
    "rate_limit_backend": "redis",
}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APP_ENV",
        "DATABASE_URL",
        "REDIS_URL",
        "RATE_LIMIT_ENABLED",
        "RATE_LIMIT_BACKEND",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)


def _prod(**overrides: Any) -> Settings:
    return load_settings(_env_file=None, app_env="production", **{**SECRETS, **SAFE, **overrides})


def test_safe_production_configuration_loads() -> None:
    settings = _prod()
    assert settings.is_production
    assert settings.docs_enabled is False
    assert settings.rate_limit_enabled is True


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"cors_allowed_origins": "http://app.example.com"}, "CORS_ALLOWED_ORIGINS"),
        ({"cors_allowed_origins": "https://ok.example,http://localhost:3000"}, "https://"),
        ({"rate_limit_backend": "memory"}, "RATE_LIMIT_BACKEND"),
        ({"log_level": "debug"}, "LOG_LEVEL"),
        ({"llm_base_url": "http://llm.internal/v1"}, "LLM_BASE_URL"),
        ({"debug": True}, "DEBUG"),
    ],
)
def test_unsafe_production_settings_are_rejected(override: dict[str, Any], message: str) -> None:
    with pytest.raises(SettingsError, match=message) as excinfo:
        _prod(**override)
    for value in SECRETS.values():
        assert value not in str(excinfo.value)


def test_development_allows_local_origins_and_memory_limiter() -> None:
    settings = load_settings(
        _env_file=None,
        app_env="development",
        **SECRETS,
        cors_allowed_origins="http://localhost:3000",
        rate_limit_backend="memory",
    )
    assert settings.docs_enabled is True


def test_http_llm_url_is_fine_in_production_when_llm_is_off() -> None:
    assert _prod(llm_provider="none", llm_base_url="http://llm.internal/v1").llm_provider == "none"


def test_docs_can_be_forced_on_in_production() -> None:
    assert _prod(api_docs_enabled=True).docs_enabled is True


def test_soft_time_limit_must_be_below_hard_limit() -> None:
    with pytest.raises(SettingsError, match="CELERY_TASK_SOFT_TIME_LIMIT"):
        load_settings(
            _env_file=None,
            app_env="test",
            jwt_secret_key="k" * 40,
            celery_task_soft_time_limit=300,
            celery_task_time_limit=300,
        )
