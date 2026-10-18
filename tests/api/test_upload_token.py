"""Upload-only tokens (POST /auth/upload-token) and the upload policy endpoint."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import UPLOAD_TOKEN_TYPE, create_upload_token, decode_access_token
from app.domain.enums import UserRole
from tests.factories import text_file


def _upload_headers(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    response = client.post("/auth/upload-token", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 300
    return {"Authorization": f"Bearer {body['upload_token']}"}


def test_upload_token_is_accepted_by_post_documents(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    upload_headers = _upload_headers(client, user_headers)
    response = client.post("/documents", files={"file": text_file()}, headers=upload_headers)
    assert response.status_code == 201, response.text
    # The document belongs to the token's user.
    listed = client.get("/documents", headers=user_headers).json()
    assert [item["id"] for item in listed["items"]] == [response.json()["id"]]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/documents"),
        ("GET", "/documents/upload-policy"),
        ("GET", "/auth/me"),
        ("POST", "/auth/upload-token"),
        ("POST", "/search"),
        ("POST", "/ask"),
        ("GET", "/audit-logs/me"),
        ("GET", f"/documents/{uuid.uuid4()}"),
        ("DELETE", f"/documents/{uuid.uuid4()}"),
        ("POST", f"/documents/{uuid.uuid4()}/reprocess"),
    ],
)
def test_upload_token_is_rejected_everywhere_else(
    client: TestClient, user_headers: dict[str, str], method: str, path: str
) -> None:
    upload_headers = _upload_headers(client, user_headers)
    json_body = {"query": "x", "question": "x"} if method == "POST" else None
    response = client.request(method, path, headers=upload_headers, json=json_body)
    assert response.status_code == 401, (path, response.text)


def test_upload_token_requires_an_access_token(client: TestClient) -> None:
    assert client.post("/auth/upload-token").status_code == 401


def test_expired_upload_token_is_rejected(
    client: TestClient, user_headers: dict[str, str], test_settings: Settings
) -> None:
    me = client.get("/auth/me", headers=user_headers).json()
    token, _ = create_upload_token(
        user_id=uuid.UUID(me["id"]),
        role=UserRole.USER,
        settings=test_settings,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    response = client.post(
        "/documents", files={"file": text_file()}, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_upload_token_claims(test_settings: Settings) -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_upload_token(
        user_id=user_id, role=UserRole.USER, settings=test_settings
    )
    payload = decode_access_token(
        token, test_settings, allowed_types=frozenset({UPLOAD_TOKEN_TYPE})
    )
    assert payload.subject == user_id
    assert expires_in == test_settings.upload_token_expire_seconds
    with pytest.raises(Exception, match="unexpected token type"):
        decode_access_token(token, test_settings)


def test_upload_policy_reflects_settings(
    client: TestClient, user_headers: dict[str, str], test_settings: Settings
) -> None:
    response = client.get("/documents/upload-policy", headers=user_headers)
    assert response.status_code == 200
    assert response.json() == {
        "max_upload_size_bytes": test_settings.max_upload_size_bytes,
        "allowed_extensions": list(test_settings.allowed_extensions),
        "allowed_content_types": list(test_settings.allowed_content_types),
    }
    assert client.get("/documents/upload-policy").status_code == 401
