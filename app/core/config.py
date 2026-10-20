"""Application settings loaded exclusively from environment variables (or a local .env file).

Connection URLs are derived from their parts (``POSTGRES_*``, ``REDIS_*``) unless an
explicit override (``DATABASE_URL``, ``REDIS_URL``, ``CELERY_*``) is given. Every secret
is a ``SecretStr`` so it is masked in ``repr`` and logs; validation errors never include
input values.
"""

import importlib.util
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL

from app.core.rate_limit import parse_rate

MIN_JWT_SECRET_LENGTH = 32
MIN_INTERNAL_SECRET_LENGTH = 32
_PLACEHOLDER_PREFIXES = ("replace-with", "change-me", "changeme", "<")


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

    app_name: str = "Document Intelligence & Analysis"
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
    # Lifetime of the upload-only token from POST /auth/upload-token.
    upload_token_expire_seconds: int = Field(default=300, ge=30, le=3600)

    storage_backend: str = "local"
    storage_path: Path = Path("./storage_data")
    # STORAGE_BACKEND=s3 (any S3-compatible service) or oci (OCI Object Storage through
    # its S3 compatibility API, https://<namespace>.compat.objectstorage.<region>.oraclecloud.com).
    storage_s3_bucket: str | None = None
    storage_s3_endpoint_url: str | None = None
    storage_s3_region: str = "us-east-1"
    storage_s3_access_key_id: SecretStr | None = None
    storage_s3_secret_access_key: SecretStr | None = None
    storage_s3_prefix: str = ""
    # path-style is what OCI's compatibility API supports; MinIO accepts both.
    storage_s3_addressing_style: Literal["path", "virtual", "auto"] = "path"
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

    # --- DIP2: document processing, retrieval and question answering ----------------
    # Models are loaded lazily on first use (worker: first document; API: first search),
    # never at startup, in health checks or in the test suite.
    # onnx: ONNX Runtime with the model's fp32 ONNX export (default, no PyTorch).
    # remote: delegate to the API's POST /internal/embed (worker on small machines, so
    # only the API holds the model). sentence-transformers: PyTorch, needs the optional
    # "torch" extra (uv sync --extra torch).
    embedding_provider: Literal["onnx", "remote", "sentence-transformers"] = "onnx"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Path of the ONNX file inside the model repository (EMBEDDING_PROVIDER=onnx).
    embedding_onnx_file: str = "onnx/model.onnx"
    # EMBEDDING_PROVIDER=remote: the API's internal endpoint, e.g. http://api:8000/internal/embed
    embedding_remote_url: str | None = None
    embedding_remote_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    # Shared secret for POST /internal/embed (X-Internal-Secret header). Unset = the
    # endpoint answers 404. Required whenever EMBEDDING_PROVIDER=remote.
    internal_embed_secret: SecretStr | None = None
    internal_embed_max_batch: int = Field(default=64, ge=1, le=512)
    internal_embed_max_text_chars: int = Field(default=8000, ge=1, le=100_000)
    # Must equal the vector column size created by migration 0002 (vector(384)). The
    # provider verifies the loaded model's dimension against this value.
    embedding_dimension: int = Field(default=384, ge=1, le=4096)
    embedding_batch_size: int = Field(default=32, ge=1, le=512)
    embedding_device: str = "cpu"
    # Intra-op threads per process for embedding/reranking (ONNX Runtime or PyTorch;
    # 0 = library default, one per core). Small models are much faster with few threads when several
    # processes share the CPU; see app/ai/embeddings.py:apply_torch_threads.
    torch_num_threads: int = Field(default=2, ge=0, le=64)
    # Prefix the model card recommends for retrieval queries (documents get no prefix).
    embedding_query_instruction: str = "Represent this sentence for searching relevant passages: "

    chunk_size: int = Field(default=400, ge=32, le=4000, description="Tokens per chunk.")
    chunk_overlap: int = Field(default=60, ge=0, le=1000, description="Tokens of overlap.")
    max_chunks_per_document: int = Field(default=1000, ge=1, le=100_000)
    # Decompressed-size ceiling for DOCX archives (zip-bomb guard).
    max_docx_uncompressed_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)

    top_k: int = Field(default=5, ge=1, le=100)
    max_top_k: int = Field(default=20, ge=1, le=100)
    candidate_k: int = Field(default=40, ge=1, le=1000)
    max_query_length: int = Field(default=1000, ge=1, le=10_000)
    # Cosine similarity a retrieved chunk needs to count as evidence for /ask. 0.48 sits
    # between the highest off-topic (0.451) and lowest on-topic (0.507) top-1 similarity
    # measured with bge-small-en-v1.5 on the small synthetic set (docs/rag.md); recalibrate
    # when the model or the corpus changes.
    min_evidence_similarity: float = Field(default=0.48, ge=-1.0, le=1.0)
    # /ask: passages retrieved (hybrid) per question when the request gives no top_k, and
    # the lowest cosine similarity a passage needs to be sent as context once the best
    # passage has passed MIN_EVIDENCE_SIMILARITY (keeps supporting passages that a
    # document-level question matches only loosely). Recalibrated 2026-10-18 with
    # scripts/calibrate_evidence_threshold.py: document-level questions 0.507-0.584,
    # off-topic 0.388-0.451 (docs/rag.md). A value above MIN_EVIDENCE_SIMILARITY is
    # capped at it.
    ask_top_k: int = Field(default=8, ge=1, le=100)
    ask_context_min_similarity: float = Field(default=0.40, ge=-1.0, le=1.0)
    # Gate used instead of MIN_EVIDENCE_SIMILARITY when the question is scoped to one
    # document (document_id) or is about the document as a whole ("summarize this
    # document", "what is this document about?"). Such questions match no single passage
    # well: measured 2026-10-19 on the check_ask_real.py sample, "What is this document
    # about?" scored 0.415 while an off-topic question scored 0.422, so similarity cannot
    # separate them; the LLM decides instead (it may answer "insufficient").
    ask_scoped_min_similarity: float = Field(default=0.20, ge=-1.0, le=1.0)

    reranking_enabled: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_top_k: int = Field(default=20, ge=1, le=200)

    # "openai": any OpenAI-compatible /chat/completions endpoint (LLM_BASE_URL) using
    # OPENAI_API_KEY. "none": /ask answers 503 when evidence exists; /search still works.
    llm_provider: Literal["openai", "none"] = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    llm_max_output_tokens: int = Field(default=900, ge=16, le=8192)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_context_tokens: int = Field(default=4000, ge=100, le=100_000)
    # Request OpenAI structured outputs (response_format json_schema, app/prompt/
    # response_schema.json). Endpoints that reject it are retried once without it.
    llm_structured_output: bool = True
    # Suggested questions: one small LLM call per processed document (worker), fed the
    # start of the document text. Failures never fail the job; the field stays null.
    # Skipped automatically when no LLM is configured or the model/base URL is a stub.
    question_suggestions_enabled: bool = True
    question_suggestions_max_input_chars: int = Field(default=10_000, ge=500, le=50_000)
    question_suggestions_max_output_tokens: int = Field(default=200, ge=50, le=1000)
    question_suggestions_timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    # --- DIP3: hardening, rate limiting, observability ----------------------------------
    # Swagger UI / ReDoc / openapi.json. None = enabled except when APP_ENV=production.
    api_docs_enabled: bool | None = None
    # Upper bound for any request body except uploads (JSON and form logins).
    max_request_body_bytes: int = Field(default=1024 * 1024, ge=1024)
    # Multipart framing allowance on top of MAX_UPLOAD_SIZE_BYTES for POST /documents.
    upload_body_overhead_bytes: int = Field(default=64 * 1024, ge=0, le=10 * 1024 * 1024)
    security_headers_enabled: bool = True

    rate_limit_enabled: bool = True
    # Shared secret that lets a trusted server-side caller (the Next.js BFF) name the real
    # client IP in X-DIP-Client-IP (with X-DIP-Client-Secret). Without it every request
    # proxied by the BFF shares the BFF's egress IP for per-IP limits (register, login,
    # demo). Empty = header ignored. Set the same value as DIP_CLIENT_IP_SECRET on the BFF.
    client_ip_header_secret: SecretStr | None = None
    # "redis": shared counters (required in production). "memory": per process (dev/tests).
    rate_limit_backend: Literal["redis", "memory"] = "redis"
    # Defaults suit a small public demo (docs/security.md#rate-limits). Keys: client IP
    # for anonymous endpoints, user id for authenticated ones, "global" for demo_global.
    rate_limit_register: str = "5/minute"
    rate_limit_register_daily: str = "20/day"
    rate_limit_login: str = "10/minute"
    rate_limit_login_per_email: str = "5/minute"
    rate_limit_upload: str = "10/minute"
    rate_limit_upload_daily: str = "100/day"
    rate_limit_upload_token: str = "30/minute"  # noqa: S105  (a rate, not a secret)
    rate_limit_search: str = "60/minute"
    rate_limit_ask: str = "10/minute"
    rate_limit_ask_daily: str = "200/day"
    rate_limit_reprocess: str = "10/minute"
    rate_limit_demo: str = "3/day"
    rate_limit_demo_global: str = "200/day"

    # --- Demo mode (POST /auth/demo; docs/demo-mode.md) ----------------------------------
    # Ephemeral, isolated demo accounts without a password login. Limits are enforced
    # server-side with counters on the user row; the account and its files are deleted
    # DEMO_TTL_HOURS after creation by the beat task "users.cleanup_expired_demos".
    demo_enabled: bool = True
    demo_max_questions: int = Field(default=3, ge=0, le=1000)
    demo_max_uploads: int = Field(default=1, ge=0, le=100)
    demo_max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    demo_allowed_extensions: Annotated[list[str], NoDecode] = ["pdf"]
    demo_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)
    demo_cleanup_interval_seconds: int = Field(default=900, ge=0)

    metrics_enabled: bool = True
    # Worker-side Prometheus exporter port (None = off). Needs PROMETHEUS_MULTIPROC_DIR
    # with the prefork pool; see docs/observability.md.
    worker_metrics_port: int | None = Field(default=None, ge=1, le=65535)

    celery_task_soft_time_limit: int = Field(default=240, ge=1)
    celery_task_time_limit: int = Field(default=300, ge=1)
    # Stale-job reconciliation (app/workers/reconcile.py): a job still "processing" or
    # "retrying" after this many seconds is failed. Must exceed CELERY_TASK_TIME_LIMIT.
    stale_job_timeout_seconds: int = Field(default=900, ge=60)
    # How often the worker's embedded beat runs the reconciler (0 = never schedule it).
    stale_job_check_interval_seconds: int = Field(default=300, ge=0)

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _parse_extensions(cls, value: object) -> object:
        parsed = _split_csv(value)
        if isinstance(parsed, list):
            return [str(item).lower().lstrip(".") for item in parsed]
        return parsed

    @field_validator("demo_allowed_extensions", mode="before")
    @classmethod
    def _parse_demo_extensions(cls, value: object) -> object:
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

    @field_validator(
        "rate_limit_register",
        "rate_limit_register_daily",
        "rate_limit_login",
        "rate_limit_login_per_email",
        "rate_limit_upload",
        "rate_limit_upload_daily",
        "rate_limit_upload_token",
        "rate_limit_search",
        "rate_limit_ask",
        "rate_limit_ask_daily",
        "rate_limit_reprocess",
        "rate_limit_demo",
        "rate_limit_demo_global",
    )
    @classmethod
    def _validate_rate(cls, value: str) -> str:
        parse_rate(value)
        return value.strip().lower()

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("CORS_ALLOWED_ORIGINS must list explicit origins; '*' is not allowed")
        return value

    @field_validator("client_ip_header_secret")
    @classmethod
    def _client_ip_secret_strength(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and 0 < len(value.get_secret_value()) < 24:
            raise ValueError("CLIENT_IP_HEADER_SECRET must be empty or at least 24 characters")
        return value

    @field_validator("internal_embed_secret")
    @classmethod
    def _internal_embed_secret_strength(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < MIN_INTERNAL_SECRET_LENGTH:
            raise ValueError(
                f"INTERNAL_EMBED_SECRET must be empty or at least {MIN_INTERNAL_SECRET_LENGTH} "
                "characters"
            )
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
        "api_docs_enabled",
        "worker_metrics_port",
        "openai_api_key",
        "postgres_password",
        "redis_password",
        "database_url",
        "redis_url",
        "celery_broker_url",
        "celery_result_backend",
        "storage_s3_bucket",
        "storage_s3_endpoint_url",
        "storage_s3_access_key_id",
        "storage_s3_secret_access_key",
        "embedding_remote_url",
        "internal_embed_secret",
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
        if self.app_env is Environment.PRODUCTION:
            problems.extend(self._production_problems())
        problems.extend(self._consistency_problems())
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def _consistency_problems(self) -> list[str]:
        problems: list[str] = []
        if self.chunk_overlap >= self.chunk_size:
            problems.append("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.ask_top_k > self.max_top_k:
            problems.append("ASK_TOP_K must not exceed MAX_TOP_K")
        if self.top_k > self.max_top_k:
            problems.append("TOP_K must not exceed MAX_TOP_K")
        if self.candidate_k < self.max_top_k:
            problems.append("CANDIDATE_K must be at least MAX_TOP_K")
        if not self.llm_base_url.startswith(("https://", "http://")):
            problems.append("LLM_BASE_URL must be an http(s) URL")
        if self.celery_task_soft_time_limit >= self.celery_task_time_limit:
            problems.append("CELERY_TASK_SOFT_TIME_LIMIT must be below CELERY_TASK_TIME_LIMIT")
        if self.stale_job_timeout_seconds <= self.celery_task_time_limit:
            problems.append("STALE_JOB_TIMEOUT_SECONDS must exceed CELERY_TASK_TIME_LIMIT")
        problems.extend(self._object_storage_problems())
        problems.extend(self._embedding_problems())
        return problems

    def _embedding_problems(self) -> list[str]:
        problems: list[str] = []
        if self.embedding_provider == "remote":
            if self.embedding_remote_url is None:
                problems.append("EMBEDDING_REMOTE_URL is required when EMBEDDING_PROVIDER=remote")
            elif not self.embedding_remote_url.startswith(("https://", "http://")):
                problems.append("EMBEDDING_REMOTE_URL must be an http(s) URL")
            if self.internal_embed_secret is None:
                problems.append("INTERNAL_EMBED_SECRET is required when EMBEDDING_PROVIDER=remote")
        torch_needed = self.embedding_provider == "sentence-transformers" or self.reranking_enabled
        if torch_needed and importlib.util.find_spec("sentence_transformers") is None:
            problems.append(
                "EMBEDDING_PROVIDER=sentence-transformers and RERANKING_ENABLED need the "
                "optional torch extra (uv sync --extra torch); use EMBEDDING_PROVIDER=onnx"
            )
        return problems

    def _object_storage_problems(self) -> list[str]:
        if self.storage_backend not in {"s3", "oci"}:
            return []
        problems: list[str] = []
        required = {
            "STORAGE_S3_BUCKET": self.storage_s3_bucket,
            "STORAGE_S3_ACCESS_KEY_ID": self.storage_s3_access_key_id,
            "STORAGE_S3_SECRET_ACCESS_KEY": self.storage_s3_secret_access_key,
        }
        if self.storage_backend == "oci":
            required["STORAGE_S3_ENDPOINT_URL"] = self.storage_s3_endpoint_url
        problems.extend(
            f"{name} is required when STORAGE_BACKEND={self.storage_backend}"
            for name, value in required.items()
            if value is None
        )
        endpoint = self.storage_s3_endpoint_url
        if endpoint is not None and not endpoint.startswith(("https://", "http://")):
            problems.append("STORAGE_S3_ENDPOINT_URL must be an http(s) URL")
        if self.storage_s3_prefix.startswith("/") or ".." in self.storage_s3_prefix:
            problems.append("STORAGE_S3_PREFIX must be a relative key prefix")
        return problems

    def _production_problems(self) -> list[str]:
        """Extra rules for APP_ENV=production (messages name settings, never values)."""
        problems: list[str] = []
        if self.debug:
            problems.append("DEBUG must be false when APP_ENV=production")
        insecure = [o for o in self.cors_allowed_origins if not o.startswith("https://")]
        if insecure:
            problems.append("CORS_ALLOWED_ORIGINS must only contain https:// origins in production")
        if self.llm_provider == "openai" and not self.llm_base_url.startswith("https://"):
            problems.append("LLM_BASE_URL must use https:// in production")
        if self.rate_limit_enabled and self.rate_limit_backend == "memory":
            problems.append("RATE_LIMIT_BACKEND=memory is per-process; use redis in production")
        if self.internal_embed_secret is not None and _is_placeholder(self.internal_embed_secret):
            problems.append("INTERNAL_EMBED_SECRET still has its .env.example placeholder value")
        if self.log_level == "DEBUG":
            problems.append("LOG_LEVEL=DEBUG is not allowed in production")
        return problems

    @property
    def docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return self.app_env is not Environment.PRODUCTION

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
