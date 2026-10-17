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
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["MAX_UPLOAD_SIZE_BYTES"] = str(64 * 1024)
os.environ["UPLOAD_CHUNK_SIZE_BYTES"] = "4096"
os.environ["LOG_LEVEL"] = "WARNING"

from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.api.dependencies.services import get_storage, get_task_dispatcher  # noqa: E402
from app.core.security import PasswordHasher  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.domain.enums import UserRole  # noqa: E402
from app.main import create_app  # noqa: E402
from app.storage.local import LocalStorage  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TABLES = ("audit_logs", "document_processing_jobs", "documents", "users")
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
def app(storage: LocalStorage, dispatcher: RecordingDispatcher) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_storage] = lambda: storage
    application.dependency_overrides[get_task_dispatcher] = lambda: dispatcher
    return application


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
