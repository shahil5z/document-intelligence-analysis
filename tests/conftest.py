"""Shared fixtures.

The suite runs against a real PostgreSQL database given by ``TEST_DATABASE_URL``
(its name must contain "test" because every table is truncated between tests).
Celery is replaced by a recording dispatcher, so no Redis is needed.
"""

import os
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
if not TEST_DATABASE_URL:
    pytest.exit("TEST_DATABASE_URL must point at a disposable PostgreSQL database", returncode=2)
if "test" not in (make_url(TEST_DATABASE_URL).database or ""):
    pytest.exit(
        "Refusing to run: TEST_DATABASE_URL database name must contain 'test'", returncode=2
    )

# Settings are read from the environment on first use, so set them before importing app.*
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["MAX_UPLOAD_SIZE_BYTES"] = str(64 * 1024)
os.environ["UPLOAD_CHUNK_SIZE_BYTES"] = "4096"
os.environ["LOG_LEVEL"] = "WARNING"

from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.api.dependencies.services import (  # noqa: E402
    get_embedder,
    get_llm,
    get_reranker,
    get_storage,
    get_task_dispatcher,
)
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.security import PasswordHasher  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.domain.enums import UserRole  # noqa: E402
from app.main import create_app  # noqa: E402
from app.processing.chunking import ApproximateTokenCounter  # noqa: E402
from app.storage.local import LocalStorage  # noqa: E402
from app.workers.processing import DocumentProcessor, JobOutcome  # noqa: E402
from app.workers.steps import build_indexing_pipeline  # noqa: E402
from tests.fakes import HashingEmbeddingProvider, MockLLM  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TABLES = ("audit_logs", "document_chunks", "document_processing_jobs", "documents", "users")
# The hashing test embedder yields lower cosine similarities than a real model, so API
# tests use a lower evidence threshold (insufficient-evidence tests use unrelated text).
TEST_MIN_EVIDENCE_SIMILARITY = 0.15
DEFAULT_PASSWORD = "a-sufficiently-long-password"


@dataclass
class RecordingDispatcher:
    calls: list[dict[str, object]] = field(default_factory=list)
    fail: bool = False

    def enqueue_processing(
        self, *, document_id: uuid.UUID, job_id: uuid.UUID, task_id: str
    ) -> None:
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.calls.append({"document_id": document_id, "job_id": job_id, "task_id": task_id})


@pytest.fixture(scope="session", autouse=True)
def _migrated_database() -> None:
    """Build the schema with the real Alembic migrations (downgrade first for a clean slate)."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.cmd_opts = None
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
    engine.dispose()


@pytest.fixture
def db_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def embedder() -> HashingEmbeddingProvider:
    return HashingEmbeddingProvider()


@pytest.fixture
def llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def test_settings() -> Settings:
    return get_settings().model_copy(
        update={"min_evidence_similarity": TEST_MIN_EVIDENCE_SIMILARITY}
    )


@pytest.fixture
def app(
    storage: LocalStorage,
    dispatcher: RecordingDispatcher,
    embedder: HashingEmbeddingProvider,
    llm: MockLLM,
    test_settings: Settings,
) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_storage] = lambda: storage
    application.dependency_overrides[get_task_dispatcher] = lambda: dispatcher
    # Never load real models or call a real LLM from the test suite.
    application.dependency_overrides[get_embedder] = lambda: embedder
    application.dependency_overrides[get_llm] = lambda: llm
    application.dependency_overrides[get_reranker] = lambda: None
    application.dependency_overrides[get_settings] = lambda: test_settings
    return application


def run_indexing(
    job_id: uuid.UUID,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    settings: Settings | None = None,
) -> JobOutcome:
    """Run the real DIP2 pipeline for one job, with the fake embedder and approx tokens."""
    processor = DocumentProcessor(
        get_session_factory(),
        storage,
        build_indexing_pipeline(
            settings=settings or get_settings(),
            session_factory=get_session_factory(),
            embedder=embedder,
            token_counter=ApproximateTokenCounter(),
        ),
    )
    return processor.run(job_id=job_id, is_final_attempt=False)


def upload_and_index(
    client: TestClient,
    headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    file: tuple[str, bytes, str],
    settings: Settings | None = None,
) -> tuple[uuid.UUID, JobOutcome]:
    response = client.post("/documents", files={"file": file}, headers=headers)
    assert response.status_code == 201, response.text
    call = dispatcher.calls[-1]
    outcome = run_indexing(call["job_id"], storage, embedder, settings)  # type: ignore[arg-type]
    return call["document_id"], outcome  # type: ignore[return-value]


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def register(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> dict[str, object]:
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def login_headers(
    client: TestClient, email: str, password: str = DEFAULT_PASSWORD
) -> dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def user_headers(client: TestClient) -> dict[str, str]:
    register(client, "alice@example.com")
    return login_headers(client, "alice@example.com")


@pytest.fixture
def other_user_headers(client: TestClient) -> dict[str, str]:
    register(client, "bob@example.com")
    return login_headers(client, "bob@example.com")


@pytest.fixture
def admin_headers(client: TestClient, db_session: Session) -> dict[str, str]:
    db_session.add(
        User(
            email="admin@example.com",
            password_hash=PasswordHasher().hash(DEFAULT_PASSWORD),
            role=UserRole.ADMIN,
        )
    )
    db_session.commit()
    return login_headers(client, "admin@example.com")
