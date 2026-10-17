"""Application settings loaded exclusively from environment variables (or a local .env file)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIN_JWT_SECRET_LENGTH = 32
_INSECURE_SECRET_MARKERS = ("change-me", "changeme", "secret", "example")


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def _split_csv(value: object) -> object:
    """Allow list settings to be written as comma-separated strings in the environment."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    app_name: str = "Document Intelligence Platform"
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://dip:dip@localhost:5432/dip"
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_task_max_retries: int = Field(default=3, ge=0, le=10)
    celery_retry_backoff_seconds: int = Field(default=10, ge=1)

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "document-intelligence-platform"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=24 * 60)

    max_upload_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    upload_chunk_size_bytes: int = Field(default=1024 * 1024, ge=1024)
    storage_path: Path = Path("./storage_data")
    allowed_extensions: Annotated[list[str], NoDecode] = ["pdf", "docx", "txt"]
    allowed_content_types: Annotated[list[str], NoDecode] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    ]

    cors_allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _parse_extensions(cls, value: object) -> object:
        parsed = _split_csv(value)
        if isinstance(parsed, list):
            return [str(item).lower().lstrip(".") for item in parsed]
        return parsed

    @field_validator("allowed_content_types", mode="before")
    @classmethod
    def _parse_content_types(cls, value: object) -> object:
        parsed = _split_csv(value)
        if isinstance(parsed, list):
            return [str(item).lower() for item in parsed]
        return parsed

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("CORS_ALLOWED_ORIGINS must list explicit origins; '*' is not allowed")
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def _restrict_algorithm(cls, value: str) -> str:
        if value not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be one of HS256, HS384, HS512")
        return value

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be a standard logging level name")
        return level

    @model_validator(mode="after")
    def _validate_secret(self) -> "Settings":
        secret = self.jwt_secret.get_secret_value()
        if len(secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters long")
        if self.environment is Environment.PRODUCTION and any(
            marker in secret.lower() for marker in _INSECURE_SECRET_MARKERS
        ):
            raise ValueError("JWT_SECRET looks like a placeholder; generate a random secret")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached, read-only after creation)."""
    return Settings()  # values (including the required JWT_SECRET) come from the environment
