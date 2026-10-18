from typing import Any
from urllib.parse import unquote, urlsplit

import pytest

from app.core.config import Settings, SettingsError, load_settings

STRONG_SECRET = "k" * 40
TRICKY_PASSWORD = "p@ss/w:rd#?%"


def _load(**overrides: Any) -> Settings:
    # _env_file=None: never read the developer's .env during tests.
    return load_settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APP_ENV",
        "DATABASE_URL",
        "REDIS_URL",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "OPENAI_API_KEY",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
    ):
        monkeypatch.delenv(name, raising=False)


def test_missing_jwt_secret_fails_with_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(SettingsError, match="JWT_SECRET_KEY is required"):
        _load(app_env="test")


def test_short_jwt_secret_is_rejected_without_echoing_it() -> None:
    with pytest.raises(SettingsError, match="at least 32") as excinfo:
        _load(app_env="test", jwt_secret_key="too-short-value")
    assert "too-short-value" not in str(excinfo.value)


def test_postgres_and_redis_passwords_required_outside_test() -> None:
    with pytest.raises(SettingsError) as excinfo:
        _load(app_env="development", jwt_secret_key=STRONG_SECRET)
    message = str(excinfo.value)
    assert "POSTGRES_PASSWORD is required" in message
    assert "REDIS_PASSWORD is required" in message


def test_passwords_optional_in_test_env() -> None:
    settings = _load(app_env="test", jwt_secret_key=STRONG_SECRET)
    assert settings.postgres_password is None


def test_placeholder_secrets_are_rejected() -> None:
    with pytest.raises(SettingsError, match="placeholder") as excinfo:
        _load(
            app_env="development",
            jwt_secret_key="replace-with-a-random-secret-of-at-least-32-characters",
            postgres_password="real-looking-password",
            redis_password="replace-with-a-random-redis-password",
        )
    assert "JWT_SECRET_KEY" in str(excinfo.value)
    assert "REDIS_PASSWORD" in str(excinfo.value)
    assert "real-looking-password" not in str(excinfo.value)


def test_debug_forbidden_in_production() -> None:
    with pytest.raises(SettingsError, match="DEBUG must be false"):
        _load(
            app_env="production",
            debug=True,
            jwt_secret_key=STRONG_SECRET,
            postgres_password="pg-password",
            redis_password="redis-password",
        )


def test_urls_are_built_from_parts_with_escaping() -> None:
    settings = _load(
        app_env="development",
        jwt_secret_key=STRONG_SECRET,
        postgres_host="db",
        postgres_port=6543,
        postgres_db="docs",
        postgres_user="svc",
        postgres_password=TRICKY_PASSWORD,
        redis_host="cache",
        redis_port=6380,
        redis_db=2,
        redis_password=TRICKY_PASSWORD,
    )
    db = urlsplit(settings.get_database_url())
    assert (db.scheme, db.hostname, db.port, db.path) == ("postgresql+psycopg", "db", 6543, "/docs")
    assert unquote(db.password or "") == TRICKY_PASSWORD
    redis = urlsplit(settings.get_redis_url())
    assert (redis.hostname, redis.port, redis.path) == ("cache", 6380, "/2")
    assert unquote(redis.password or "") == TRICKY_PASSWORD
    assert settings.get_celery_broker_url() == settings.get_redis_url()
    assert settings.get_celery_result_backend() == settings.get_redis_url()


def test_explicit_urls_override_parts() -> None:
    settings = _load(
        app_env="development",
        jwt_secret_key=STRONG_SECRET,
        database_url="postgresql+psycopg://u:p@h:1/d",
        redis_url="redis://:p@r:2/0",
        celery_broker_url="redis://:p@b:3/0",
    )
    assert settings.get_database_url() == "postgresql+psycopg://u:p@h:1/d"
    assert settings.get_redis_url() == "redis://:p@r:2/0"
    assert settings.get_celery_broker_url() == "redis://:p@b:3/0"


def test_secrets_are_masked_in_repr() -> None:
    settings = _load(
        app_env="development",
        jwt_secret_key=STRONG_SECRET,
        postgres_password="pg-secret-value",
        redis_password="redis-secret-value",
        openai_api_key="openai-secret-value",
    )
    text = repr(settings) + str(settings.model_dump())
    for value in (STRONG_SECRET, "pg-secret-value", "redis-secret-value", "openai-secret-value"):
        assert value not in text


def test_openai_key_is_optional() -> None:
    assert _load(app_env="test", jwt_secret_key=STRONG_SECRET).openai_api_key is None


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(SettingsError, match="not allowed"):
        _load(app_env="test", jwt_secret_key=STRONG_SECRET, cors_allowed_origins="*")


def test_csv_lists_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_EXTENSIONS", ".PDF, txt")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com,http://localhost:3000")
    settings = _load(app_env="test", jwt_secret_key=STRONG_SECRET)
    assert settings.allowed_extensions == ["pdf", "txt"]
    assert settings.cors_allowed_origins == ["https://app.example.com", "http://localhost:3000"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"chunk_size": 100, "chunk_overlap": 100}, "CHUNK_OVERLAP must be smaller"),
        ({"top_k": 30, "max_top_k": 20}, "TOP_K must not exceed MAX_TOP_K"),
        ({"candidate_k": 5, "max_top_k": 20}, "CANDIDATE_K must be at least MAX_TOP_K"),
        ({"llm_base_url": "ftp://example.com"}, "LLM_BASE_URL"),
        ({"llm_provider": "anthropic"}, "LLM_PROVIDER"),
        ({"embedding_provider": "openai"}, "EMBEDDING_PROVIDER"),
    ],
)
def test_dip2_settings_are_validated(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        load_settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40, **overrides)


def test_dip2_defaults() -> None:
    settings = load_settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40)
    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"
    assert settings.embedding_dimension == 384
    assert (settings.chunk_size, settings.chunk_overlap) == (400, 60)
    assert settings.reranking_enabled is False
    assert settings.llm_provider == "openai"
