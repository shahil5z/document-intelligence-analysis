from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, User
from tests.conftest import DEFAULT_PASSWORD, login_headers, register


def test_register_creates_regular_user(client: TestClient, db_session: Session) -> None:
    body = register(client, "New.User@Example.com")
    assert body["email"] == "new.user@example.com"
    assert body["role"] == "user"
    assert "password" not in body
    assert "password_hash" not in body
    user = db_session.scalar(select(User).where(User.email == "new.user@example.com"))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")


def test_register_ignores_role_field(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"email": "sneaky@example.com", "password": DEFAULT_PASSWORD, "role": "admin"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "user"


def test_duplicate_register_returns_409(client: TestClient) -> None:
    register(client, "dup@example.com")
    response = client.post(
        "/auth/register", json={"email": "DUP@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_register_validates_password_length_without_echoing_it(client: TestClient) -> None:
    response = client.post("/auth/register", json={"email": "a@example.com", "password": "Zq7#pw"})
    assert response.status_code == 422
    assert "Zq7#pw" not in response.text


def test_login_success_returns_bearer_token(client: TestClient) -> None:
    register(client, "login@example.com")
    response = client.post(
        "/auth/login", json={"email": "login@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["access_token"].count(".") == 2


def test_oauth2_form_login_works(client: TestClient) -> None:
    register(client, "form@example.com")
    response = client.post(
        "/auth/token", data={"username": "form@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_with_wrong_password_returns_401(client: TestClient, db_session: Session) -> None:
    register(client, "wrong@example.com")
    response = client.post(
        "/auth/login", json={"email": "wrong@example.com", "password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Incorrect email or password"
    actions = db_session.scalars(select(AuditLog.action)).all()
    assert "user.login_failed" in actions


def test_login_with_unknown_email_returns_same_401(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Incorrect email or password"


def test_inactive_user_cannot_log_in(client: TestClient, db_session: Session) -> None:
    register(client, "inactive@example.com")
    user = db_session.scalar(select(User).where(User.email == "inactive@example.com"))
    assert user is not None
    user.is_active = False
    db_session.commit()
    response = client.post(
        "/auth/login", json={"email": "inactive@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 403


def test_me_returns_current_user(client: TestClient, user_headers: dict[str, str]) -> None:
    response = client.get("/auth/me", headers=user_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


def test_me_without_token_returns_401(client: TestClient) -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_with_garbage_token_returns_401(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_deactivated_user_token_is_rejected(client: TestClient, db_session: Session) -> None:
    register(client, "later@example.com")
    headers = login_headers(client, "later@example.com")
    user = db_session.scalar(select(User).where(User.email == "later@example.com"))
    assert user is not None
    user.is_active = False
    db_session.commit()
    assert client.get("/auth/me", headers=headers).status_code == 403


def test_register_and_login_are_audited(client: TestClient, db_session: Session) -> None:
    register(client, "audited@example.com")
    login_headers(client, "audited@example.com")
    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert {"user.registered", "user.login"} <= actions
