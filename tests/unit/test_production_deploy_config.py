"""Production deployment files: .env.production.example and app/gunicorn_conf.py."""

import importlib
import sys
from pathlib import Path

import pytest

from app.core.config import Settings, SettingsError, load_settings

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / ".env.production.example"
STRONG_SECRET = "s" * 48

# Variables read by docker-compose.prod.yml / scripts rather than by Settings.
DEPLOYMENT_ONLY_KEYS = {
    "API_DOMAIN",
    "CADDY_TLS",
    "WEB_CONCURRENCY",
    "WORKER_CONCURRENCY",
    "BACKUP_DIR",
    "BACKUP_RETENTION_DAYS",
    "BACKUP_GPG_RECIPIENT",
    "BACKUP_S3_BUCKET",
}


def _example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def test_example_only_uses_known_variables() -> None:
    fields = {name.upper() for name in Settings.model_fields}
    unknown = set(_example_values()) - fields - DEPLOYMENT_ONLY_KEYS
    assert not unknown


def test_example_contains_no_real_secret_values() -> None:
    values = _example_values()
    for key in ("JWT_SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD"):
        assert values[key].startswith("<")
    for key in ("OPENAI_API_KEY", "STORAGE_S3_ACCESS_KEY_ID", "STORAGE_S3_SECRET_ACCESS_KEY"):
        assert values[key] == ""


def test_unfilled_example_is_rejected_at_startup() -> None:
    values = {k.lower(): v for k, v in _example_values().items() if k not in DEPLOYMENT_ONLY_KEYS}
    with pytest.raises(SettingsError) as excinfo:
        load_settings(_env_file=None, **values)
    message = str(excinfo.value)
    assert "JWT_SECRET_KEY" in message
    assert "POSTGRES_PASSWORD" in message
    assert "CORS_ALLOWED_ORIGINS must only contain https://" in message


def test_filled_example_is_a_valid_production_configuration() -> None:
    values = {k.lower(): v for k, v in _example_values().items() if k not in DEPLOYMENT_ONLY_KEYS}
    values |= {
        "jwt_secret_key": STRONG_SECRET,
        "postgres_password": "p" * 24,
        "redis_password": "r" * 24,
        "cors_allowed_origins": "https://dip-demo.vercel.app",
    }
    settings = load_settings(_env_file=None, **values)
    assert settings.is_production
    assert settings.openai_api_key is None
    assert settings.rate_limit_ask == "20/hour"
    assert settings.storage_backend == "local"


def _reload_gunicorn_conf(monkeypatch: pytest.MonkeyPatch, **env: str) -> object:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("app.gunicorn_conf", None)
    return importlib.import_module("app.gunicorn_conf")


def test_gunicorn_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("WEB_CONCURRENCY", "GUNICORN_TIMEOUT", "FORWARDED_ALLOW_IPS"):
        monkeypatch.delenv(key, raising=False)
    conf = _reload_gunicorn_conf(monkeypatch)
    assert conf.workers == 2  # type: ignore[attr-defined]
    assert conf.worker_class == "uvicorn_worker.UvicornWorker"  # type: ignore[attr-defined]
    assert conf.bind == "0.0.0.0:8000"  # type: ignore[attr-defined]
    assert conf.accesslog is None  # type: ignore[attr-defined]


def test_gunicorn_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = _reload_gunicorn_conf(
        monkeypatch, WEB_CONCURRENCY="3", GUNICORN_TIMEOUT="90", FORWARDED_ALLOW_IPS="172.18.0.2"
    )
    assert conf.workers == 3  # type: ignore[attr-defined]
    assert conf.timeout == 90  # type: ignore[attr-defined]
    assert conf.forwarded_allow_ips == "172.18.0.2"  # type: ignore[attr-defined]


def test_gunicorn_worker_class_is_importable() -> None:
    module = importlib.import_module("uvicorn_worker")
    assert hasattr(module, "UvicornWorker")
