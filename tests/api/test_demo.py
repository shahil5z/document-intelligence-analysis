"""Demo mode: creation, limits, isolation, conversion, expiry and rate limits."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies.services import (
    get_embedder,
    get_llm,
    get_reranker,
    get_storage,
    get_task_dispatcher,
)
from app.core.config import Settings, get_settings
from app.core.security import PasswordHasher
from app.db.models import Document, DocumentChunk, User
from app.db.repositories.users import UserRepository
from app.db.session import get_session_factory
from app.main import create_app
from app.services.demo_service import DEMO_EMAIL_DOMAIN, cleanup_expired_demo_users
from app.storage.local import LocalStorage
from tests.conftest import (
    DEFAULT_PASSWORD,
    RecordingDispatcher,
    login_headers,
    register,
    run_indexing,
)
from tests.fakes import HashingEmbeddingProvider, MockLLM
from tests.fixtures.builders import build_pdf

POLICY = [
    [
        "Refund policy. Customers may request a refund within 30 days of delivery.",
        "Refunds are paid to the original payment method within seven business days.",
    ]
]
ANSWER = (
    '{"status": "answered", "answer": "Refunds are possible within 30 days [1].", '
    '"citations": [1], "missing_information": ""}'
)
OFF_TOPIC = "quantum chromodynamics lattice gauge"


def _make_app(
    settings: Settings,
    storage: LocalStorage,
    dispatcher: RecordingDispatcher,
    embedder: HashingEmbeddingProvider,
    llm: MockLLM,
) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[get_storage] = lambda: storage
    application.dependency_overrides[get_task_dispatcher] = lambda: dispatcher
    application.dependency_overrides[get_embedder] = lambda: embedder
    application.dependency_overrides[get_llm] = lambda: llm
    application.dependency_overrides[get_reranker] = lambda: None
    application.dependency_overrides[get_settings] = lambda: settings
    return application


@pytest.fixture
def demo_settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"demo_max_upload_bytes": 64 * 1024})


@pytest.fixture
def demo_client(
    database: None,
    demo_settings: Settings,
    storage: LocalStorage,
    dispatcher: RecordingDispatcher,
    embedder: HashingEmbeddingProvider,
    llm: MockLLM,
) -> Iterator[TestClient]:
    llm.response = ANSWER
    app = _make_app(demo_settings, storage, dispatcher, embedder, llm)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _start(client: TestClient) -> tuple[dict[str, str], dict[str, Any]]:
    response = client.post("/auth/demo")
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


def _upload_pdf(
    client: TestClient,
    headers: dict[str, str],
    pages: list[list[str]] | None = None,
    name: str = "policy.pdf",
) -> Any:
    return client.post(
        "/documents",
        files={"file": (name, build_pdf(pages or POLICY), "application/pdf")},
        headers=headers,
    )


def _index_last(
    dispatcher: RecordingDispatcher, storage: LocalStorage, embedder: HashingEmbeddingProvider
) -> None:
    call = dispatcher.calls[-1]
    run_indexing(call["job_id"], storage, embedder)  # type: ignore[arg-type]


def _demo_limit(response: Any) -> str:
    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "demo_limit_reached"
    limit: str = error["details"][0]["limit"]
    return limit


def test_start_demo_returns_an_isolated_demo_account(demo_client: TestClient) -> None:
    headers, body = _start(demo_client)
    assert body["token_type"] == "bearer"
    assert 0 < body["expires_in"] <= 2 * 3600
    assert body["demo"]["questions_limit"] == 3
    assert body["demo"]["questions_remaining"] == 3
    assert body["demo"]["uploads_limit"] == 1
    assert body["demo"]["allowed_extensions"] == ["pdf"]
    me = demo_client.get("/auth/me", headers=headers).json()
    assert me["is_demo"] is True
    assert me["role"] == "user"
    assert me["email"].endswith("@" + DEMO_EMAIL_DOMAIN)
    assert me["demo"]["expires_at"] is not None
    other_headers, _ = _start(demo_client)
    assert demo_client.get("/auth/me", headers=other_headers).json()["id"] != me["id"]


def test_regular_users_have_no_demo_block(
    demo_client: TestClient,
) -> None:
    register(demo_client, "carol@example.com")
    me = demo_client.get("/auth/me", headers=login_headers(demo_client, "carol@example.com"))
    assert me.json()["is_demo"] is False
    assert me.json()["demo"] is None


def test_demo_accounts_cannot_log_in_with_a_password(
    demo_client: TestClient, db_session: Session
) -> None:
    headers, _ = _start(demo_client)
    email = demo_client.get("/auth/me", headers=headers).json()["email"]
    user = db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    # The demo address (*.invalid) is not even accepted by the login schema...
    response = demo_client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
    assert response.status_code == 422
    # ...and with a deliverable address and a known password the login is still refused.
    user.email = "demo-login@example.com"
    user.password_hash = PasswordHasher().hash(DEFAULT_PASSWORD)
    db_session.commit()
    response = demo_client.post(
        "/auth/login", json={"email": "demo-login@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 401


def test_one_pdf_upload_then_demo_limit(demo_client: TestClient) -> None:
    headers, _ = _start(demo_client)
    assert _upload_pdf(demo_client, headers).status_code == 201
    second = _upload_pdf(demo_client, headers, [["Another document entirely."]], "b.pdf")
    assert _demo_limit(second) == "uploads"
    me = demo_client.get("/auth/me", headers=headers).json()
    assert me["demo"]["uploads_used"] == 1


def test_demo_rejects_other_file_types_without_using_the_upload(
    demo_client: TestClient,
) -> None:
    headers, _ = _start(demo_client)
    txt = demo_client.post(
        "/documents", files={"file": ("a.txt", b"plain text", "text/plain")}, headers=headers
    )
    assert _demo_limit(txt) == "file_type"
    assert _upload_pdf(demo_client, headers).status_code == 201


def test_demo_size_limit_does_not_use_the_upload(
    demo_settings: Settings,
    storage: LocalStorage,
    dispatcher: RecordingDispatcher,
    embedder: HashingEmbeddingProvider,
    llm: MockLLM,
    database: None,
) -> None:
    settings = demo_settings.model_copy(update={"demo_max_upload_bytes": 1024})
    app = _make_app(settings, storage, dispatcher, embedder, llm)
    with TestClient(app, raise_server_exceptions=False) as client:
        headers, body = _start(client)
        assert body["demo"]["max_upload_bytes"] == 1024
        big = [[f"Line {i} of a long document about refunds and returns." for i in range(60)]]
        response = _upload_pdf(client, headers, big)
        assert _demo_limit(response) == "file_size"
        assert "1 KB" not in response.json()["error"]["message"]
        assert client.get("/auth/me", headers=headers).json()["demo"]["uploads_used"] == 0
        assert _upload_pdf(client, headers, [["Tiny."]]).status_code == 201


def test_three_questions_then_demo_limit(
    demo_client: TestClient,
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    llm: MockLLM,
) -> None:
    headers, _ = _start(demo_client)
    assert _upload_pdf(demo_client, headers).status_code == 201
    _index_last(dispatcher, storage, embedder)
    remaining = []
    for _ in range(3):
        response = demo_client.post(
            "/ask", json={"question": "How many days for a refund?"}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["insufficient_evidence"] is False
        remaining.append(response.json()["demo_questions_remaining"])
    assert remaining == [2, 1, 0]
    fourth = demo_client.post("/ask", json={"question": "Refund days?"}, headers=headers)
    assert _demo_limit(fourth) == "questions"
    assert len(llm.calls) == 3
    # Search stays available to demo users.
    search = demo_client.post("/search", json={"query": "refund"}, headers=headers)
    assert search.status_code == 200
    assert search.json()["results"]


def test_questions_that_never_reach_the_llm_are_not_counted(
    demo_client: TestClient,
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
    llm: MockLLM,
) -> None:
    headers, _ = _start(demo_client)
    assert _upload_pdf(demo_client, headers).status_code == 201
    _index_last(dispatcher, storage, embedder)
    below = demo_client.post("/ask", json={"question": OFF_TOPIC}, headers=headers)
    assert below.json()["insufficient_reason"] == "below_threshold"
    assert below.json()["demo_questions_remaining"] == 3
    llm.error = True
    failed = demo_client.post("/ask", json={"question": "Refund days?"}, headers=headers)
    assert failed.status_code == 503
    me = demo_client.get("/auth/me", headers=headers).json()
    assert me["demo"]["questions_used"] == 0


def test_regular_users_are_not_limited_by_demo_counters(
    demo_client: TestClient,
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> None:
    register(demo_client, "dave@example.com")
    headers = login_headers(demo_client, "dave@example.com")
    for index in range(2):
        response = _upload_pdf(demo_client, headers, [[f"Document {index} about refunds."]])
        assert response.status_code == 201
    response = demo_client.post(
        "/documents",
        files={"file": ("n.txt", b"Refunds in 30 days.", "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201
    _index_last(dispatcher, storage, embedder)
    for _ in range(4):
        response = demo_client.post("/ask", json={"question": "Refund days?"}, headers=headers)
        assert response.status_code == 200
        assert response.json()["demo_questions_remaining"] is None


def test_demo_users_are_isolated_from_other_users(
    demo_client: TestClient,
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> None:
    register(demo_client, "erin@example.com")
    erin = login_headers(demo_client, "erin@example.com")
    assert _upload_pdf(demo_client, erin).status_code == 201
    erin_doc = dispatcher.calls[-1]["document_id"]
    _index_last(dispatcher, storage, embedder)
    demo, _ = _start(demo_client)
    assert demo_client.get(f"/documents/{erin_doc}", headers=demo).status_code == 404
    assert demo_client.get("/documents", headers=demo).json()["total"] == 0
    search = demo_client.post("/search", json={"query": "refund"}, headers=demo)
    assert search.json()["results"] == []
    ask = demo_client.post("/ask", json={"question": "Refund days?"}, headers=demo)
    assert ask.json()["insufficient_evidence"] is True
    assert ask.json()["demo_questions_remaining"] == 3
    assert demo_client.get("/admin/users", headers=demo).status_code == 403


def test_convert_demo_to_a_free_account_keeps_documents(
    demo_client: TestClient,
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> None:
    headers, _ = _start(demo_client)
    assert _upload_pdf(demo_client, headers).status_code == 201
    _index_last(dispatcher, storage, embedder)
    for _ in range(3):
        demo_client.post("/ask", json={"question": "Refund days?"}, headers=headers)
    response = demo_client.post(
        "/auth/demo/convert",
        json={"email": "Frank@Example.com", "password": DEFAULT_PASSWORD},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_demo"] is False
    assert response.json()["email"] == "frank@example.com"
    assert response.json()["demo"] is None
    new_headers = login_headers(demo_client, "frank@example.com")
    assert demo_client.get("/documents", headers=new_headers).json()["total"] == 1
    ask = demo_client.post("/ask", json={"question": "Refund days?"}, headers=new_headers)
    assert ask.status_code == 200
    again = demo_client.post(
        "/auth/demo/convert",
        json={"email": "frank2@example.com", "password": DEFAULT_PASSWORD},
        headers=new_headers,
    )
    assert again.status_code == 403


def test_convert_rejects_an_existing_email(demo_client: TestClient) -> None:
    register(demo_client, "gina@example.com")
    headers, _ = _start(demo_client)
    response = demo_client.post(
        "/auth/demo/convert",
        json={"email": "gina@example.com", "password": DEFAULT_PASSWORD},
        headers=headers,
    )
    assert response.status_code == 409


def test_expired_demo_is_refused_and_cleaned_up_with_its_files(
    demo_client: TestClient,
    db_session: Session,
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> None:
    headers, _ = _start(demo_client)
    assert _upload_pdf(demo_client, headers).status_code == 201
    _index_last(dispatcher, storage, embedder)
    register(demo_client, "hank@example.com")
    hank = login_headers(demo_client, "hank@example.com")
    assert _upload_pdf(demo_client, hank, [["Hank keeps his file."]]).status_code == 201
    fresh, _ = _start(demo_client)

    demo_id = uuid.UUID(demo_client.get("/auth/me", headers=headers).json()["id"])
    demo_doc = db_session.scalar(select(Document).where(Document.owner_id == demo_id))
    assert demo_doc is not None
    demo_key = demo_doc.storage_key
    assert storage.exists(demo_key)
    user = db_session.get(User, demo_id)
    assert user is not None
    user.demo_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    assert demo_client.get("/auth/me", headers=headers).status_code == 401
    deleted = cleanup_expired_demo_users(get_session_factory(), storage)
    assert deleted == 1
    db_session.expire_all()
    assert db_session.get(User, demo_id) is None
    assert not storage.exists(demo_key)
    chunks = db_session.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.owner_id == demo_id)
    )
    assert chunks == 0
    assert demo_client.get("/documents", headers=hank).json()["total"] == 1
    assert demo_client.get("/auth/me", headers=fresh).status_code == 200
    assert cleanup_expired_demo_users(get_session_factory(), storage) == 0


def test_cleanup_handles_more_than_one_batch(db_session: Session, storage: LocalStorage) -> None:
    users = UserRepository(db_session)
    past = datetime.now(UTC) - timedelta(hours=1)
    for index in range(5):
        users.add_demo(email=f"demo-{index}@demo.invalid", password_hash="x", expires_at=past)
    db_session.commit()
    assert cleanup_expired_demo_users(get_session_factory(), storage, batch=2) == 5


def test_demo_counters_are_atomic(db_session: Session) -> None:
    users = UserRepository(db_session)
    user = users.add_demo(
        email="demo-atomic@demo.invalid",
        password_hash="x",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.commit()
    results = [users.reserve_demo_question(user.id, 3) for _ in range(5)]
    assert results == [1, 2, 3, None, None]
    uploads = [users.reserve_demo_upload(user.id, 1) for _ in range(2)]
    assert uploads == [1, None]


def test_demo_can_be_disabled(
    demo_settings: Settings,
    storage: LocalStorage,
    dispatcher: RecordingDispatcher,
    embedder: HashingEmbeddingProvider,
    llm: MockLLM,
    database: None,
) -> None:
    settings = demo_settings.model_copy(update={"demo_enabled": False})
    with TestClient(_make_app(settings, storage, dispatcher, embedder, llm)) as client:
        assert _demo_limit(client.post("/auth/demo")) == "disabled"


def test_demo_creation_is_rate_limited_per_ip_and_globally(
    demo_settings: Settings,
    storage: LocalStorage,
    dispatcher: RecordingDispatcher,
    embedder: HashingEmbeddingProvider,
    llm: MockLLM,
    database: None,
) -> None:
    per_ip = demo_settings.model_copy(
        update={"rate_limit_enabled": True, "rate_limit_backend": "memory"}
    )
    with TestClient(_make_app(per_ip, storage, dispatcher, embedder, llm)) as client:
        statuses = [client.post("/auth/demo").status_code for _ in range(4)]
        blocked = client.post("/auth/demo")
    assert statuses == [201, 201, 201, 429]  # default RATE_LIMIT_DEMO=3/day
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1

    global_cap = per_ip.model_copy(
        update={"rate_limit_demo": "100/day", "rate_limit_demo_global": "2/day"}
    )
    with TestClient(_make_app(global_cap, storage, dispatcher, embedder, llm)) as client:
        statuses = [client.post("/auth/demo").status_code for _ in range(3)]
    assert statuses == [201, 201, 429]
