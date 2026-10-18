"""Cross-user isolation matrix and upload hardening against the real database."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document
from app.storage.local import LocalStorage
from tests.conftest import RecordingDispatcher, upload_and_index
from tests.factories import pdf_file
from tests.fakes import HashingEmbeddingProvider

SECRET_TEXT = "Alice private salary band is forty two thousand credits per quarter."


@pytest.fixture
def alice_document(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    storage: LocalStorage,
    embedder: HashingEmbeddingProvider,
) -> uuid.UUID:
    document_id, outcome = upload_and_index(
        client,
        user_headers,
        dispatcher,
        storage,
        embedder,
        ("salary.txt", SECRET_TEXT.encode(), "text/plain"),
    )
    assert outcome.value == "completed"
    return document_id


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/documents/{id}", None),
        ("GET", "/documents/{id}/status", None),
        ("POST", "/documents/{id}/reprocess", None),
        ("DELETE", "/documents/{id}", None),
        ("POST", "/search", {"query": "salary band", "document_id": "{id}"}),
        ("POST", "/ask", {"question": "What is the salary band?", "document_id": "{id}"}),
    ],
)
def test_other_user_gets_404_everywhere_and_nothing_changes(
    client: TestClient,
    alice_document: uuid.UUID,
    user_headers: dict[str, str],
    other_user_headers: dict[str, str],
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    url = path.replace("{id}", str(alice_document))
    json_body = (
        {k: (str(alice_document) if v == "{id}" else v) for k, v in body.items()} if body else None
    )
    response = client.request(method, url, json=json_body, headers=other_user_headers)
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
    assert SECRET_TEXT[:20] not in response.text
    # Alice's document is untouched and still searchable by Alice.
    status = client.get(f"/documents/{alice_document}/status", headers=user_headers)
    assert status.json()["status"] == "completed"


def test_other_user_search_and_ask_without_filter_see_nothing(
    client: TestClient, alice_document: uuid.UUID, other_user_headers: dict[str, str]
) -> None:
    del alice_document
    for mode in ("semantic", "keyword", "hybrid"):
        response = client.post(
            "/search",
            json={"query": "salary band credits", "mode": mode},
            headers=other_user_headers,
        )
        assert response.status_code == 200
        assert response.json()["results"] == []
    ask = client.post("/ask", json={"question": "salary band?"}, headers=other_user_headers)
    assert ask.status_code == 200
    assert ask.json()["insufficient_evidence"] is True
    assert SECRET_TEXT[:20] not in ask.text


def test_tampered_token_role_claim_does_not_grant_admin(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    import base64  # noqa: PLC0415
    import json  # noqa: PLC0415

    token = user_headers["Authorization"].removeprefix("Bearer ")
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["role"] = "admin"
    forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    forged = {"Authorization": f"Bearer {header}.{forged_payload}.{signature}"}
    assert client.get("/admin/users", headers=forged).status_code == 401
    assert client.get("/admin/users", headers=user_headers).status_code == 403


def test_token_of_deleted_user_is_rejected(
    client: TestClient, user_headers: dict[str, str], db_session: Session
) -> None:
    from app.db.models import User  # noqa: PLC0415

    user = db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    db_session.delete(user)
    db_session.commit()
    assert client.get("/auth/me", headers=user_headers).status_code == 401


@pytest.mark.parametrize(
    "raw_name",
    [
        "../../etc/passwd.txt",
        "..\\..\\windows\\system32\\evil.txt",
        "/abs/path/notes.txt",
        "na\u202emetxt.txt",
        "<script>alert(1)</script>.txt",
    ],
)
def test_hostile_filenames_are_sanitised_and_never_used_for_storage(
    client: TestClient,
    user_headers: dict[str, str],
    db_session: Session,
    storage: LocalStorage,
    raw_name: str,
) -> None:
    response = client.post(
        "/documents",
        files={"file": (raw_name, f"content for {raw_name}".encode(), "text/plain")},
        headers=user_headers,
    )
    assert response.status_code == 201, response.text
    document = db_session.get(Document, uuid.UUID(response.json()["id"]))
    assert document is not None
    for bad in ("/", "\\", "..", "<", ">", "\u202e"):
        assert bad not in document.original_filename
    assert document.original_filename.endswith(".txt")
    assert document.storage_key == f"documents/{document.owner_id}/{document.id.hex}.txt"
    assert storage.exists(document.storage_key)


def test_upload_far_above_limit_is_rejected_by_body_limit(
    client: TestClient, user_headers: dict[str, str], db_session: Session
) -> None:
    # MAX_UPLOAD_SIZE_BYTES is 64 KiB here; 1 MiB exceeds limit + multipart allowance.
    big = pdf_file(extra=b"0" * (1024 * 1024))
    response = client.post("/documents", files={"file": big}, headers=user_headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert db_session.scalars(select(Document)).all() == []


def test_reprocess_twice_conflicts_instead_of_creating_two_jobs(
    client: TestClient, alice_document: uuid.UUID, user_headers: dict[str, str]
) -> None:
    first = client.post(f"/documents/{alice_document}/reprocess", headers=user_headers)
    second = client.post(f"/documents/{alice_document}/reprocess", headers=user_headers)
    assert first.status_code == 202
    assert second.status_code == 409
