import pytest
from pydantic import ValidationError

from app.core.config import Settings

STRONG_SECRET = "k" * 40


def test_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(jwt_secret="too-short")  # type: ignore[arg-type]


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        Settings(jwt_secret=STRONG_SECRET, cors_allowed_origins="*")  # type: ignore[arg-type]


def test_placeholder_secret_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(
            jwt_secret="change-me-change-me-change-me-change-me",  # type: ignore[arg-type]
            environment="production",  # type: ignore[arg-type]
        )


def test_csv_lists_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_EXTENSIONS", ".PDF, txt")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com,http://localhost:3000")
    settings = Settings(jwt_secret=STRONG_SECRET)  # type: ignore[arg-type]
    assert settings.allowed_extensions == ["pdf", "txt"]
    assert settings.cors_allowed_origins == ["https://app.example.com", "http://localhost:3000"]
