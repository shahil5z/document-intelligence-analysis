"""Application settings loaded exclusively from environment variables (or a local .env file).

Connection URLs are derived from their parts (``POSTGRES_*``, ``REDIS_*``) unless an
explicit override (``DATABASE_URL``, ``REDIS_URL``, ``CELERY_*``) is given. Every secret
is a ``SecretStr`` so it is masked in ``repr`` and logs; validation errors never include
input values.
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL

MIN_JWT_SECRET_LENGTH = 32
_PLACEHOLDER_PREFIXES = ("replace-with", "change-me", "changeme")


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class SettingsError(RuntimeError):
    """Raised at startup when configuration is missing or invalid. Never contains values."""


def _split_csv(value: object) -> object:
    """Allow list settings to be written as comma-separated strings in the environment."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _is_placeholder(secret: SecretStr | None) -> bool:
    return secret is not None and secret.get_secret_value().lower().startswith(
        _PLACEHOLDER_PREFIXES
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
        hide_input_in_errors=True,
    )

    app_name: str = "Document Intelligence Platform"
    app_env: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "dip"
    postgres_user: str = "dip"
    postgres_password: SecretStr | None = None
    database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0, le=15)
    redis_password: SecretStr | None = None
    redis_url: SecretStr | None = None
    celery_broker_url: SecretStr | None = None
    celery_result_backend: SecretStr | None = None
    celery_task_max_retries: int = Field(default=3, ge=0, le=10)
    celery_retry_backoff_seconds: int = Field(default=10, ge=1)

    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "document-intelligence-platform"
    jwt_access_token_expire_minutes: int = Field(default=30, ge=1, le=24 * 60)

    storage_backend: str = "local"
    storage_path: Path = Path("./storage_data")
    max_upload_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    upload_chunk_size_bytes: int = Field(default=1024 * 1024, ge=1024)
    allowed_extensions: Annotated[list[str], NoDecode] = ["pdf", "docx", "txt"]
    allowed_content_types: Annotated[list[str], NoDecode] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    ]

    # Optional: only needed by DIP2 features. Nothing calls OpenAI at startup or in health.
    openai_api_key: SecretStr | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = Field(default=30.0, gt=0)

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

    @field_validator("storage_backend")
    @classmethod
    def _normalise_storage_backend(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator(
        "openai_api_key",
        "postgres_password",
        "redis_password",
        "database_url",
        "redis_url",
        "celery_broker_url",
        "celery_result_backend",
        mode="before",
    )
    @classmethod
    def _empty_string_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        problems: list[str] = []
        if len(self.jwt_secret_key.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
            problems.append(f"JWT_SECRET_KEY must be at least {MIN_JWT_SECRET_LENGTH} characters")
        if self.app_env is not Environment.TEST:
            if self.postgres_password is None and self.database_url is None:
                problems.append("POSTGRES_PASSWORD is required (or set DATABASE_URL)")
            if self.redis_password is None and self.redis_url is None:
                problems.append("REDIS_PASSWORD is required (or set REDIS_URL)")
            for name in ("jwt_secret_key", "postgres_password", "redis_password"):
                if _is_placeholder(getattr(self, name)):
                    problems.append(
                        f"{name.upper()} still has its .env.example placeholder value; "
                        "run scripts/generate_env.py"
                    )
        if self.app_env is Environment.PRODUCTION and self.debug:
            problems.append("DEBUG must be false when APP_ENV=production")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    def get_database_url(self) -> str:
        """SQLAlchemy URL: ``DATABASE_URL`` if set, else built from ``POSTGRES_*`` (escaped)."""
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        url = URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value() if self.postgres_password else None,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
        return url.render_as_string(hide_password=False)

    def get_redis_url(self) -> str:
        """Redis URL: ``REDIS_URL`` if set, else built from ``REDIS_*`` with the password."""
        if self.redis_url is not None:
            return self.redis_url.get_secret_value()
        auth = ""
        if self.redis_password is not None:
            auth = f":{quote(self.redis_password.get_secret_value(), safe='')}@"
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def get_celery_broker_url(self) -> str:
        if self.celery_broker_url is not None:
            return self.celery_broker_url.get_secret_value()
        return self.get_redis_url()

    def get_celery_result_backend(self) -> str:
        # Task results are not stored (state lives in PostgreSQL); the backend only needs
        # to be reachable, so it defaults to the broker's Redis database.
        if self.celery_result_backend is not None:
            return self.celery_result_backend.get_secret_value()
        return self.get_redis_url()


def _describe(error: Any) -> str:
    location = ".".join(str(part) for part in error.get("loc", ())) or "settings"
    message = str(error.get("msg", "invalid value")).removeprefix("Value error, ")
    if error.get("type") == "missing":
        return f"{location.upper()} is required but not set"
    return message if location == "settings" else f"{location.upper()}: {message}"


def load_settings(**overrides: Any) -> Settings:
    """Build settings, turning validation failures into a value-free ``SettingsError``."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        details = "; ".join(_describe(error) for error in exc.errors(include_input=False))
        raise SettingsError(f"Invalid configuration: {details}") from None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached, read-only after creation)."""
    return load_settings()
