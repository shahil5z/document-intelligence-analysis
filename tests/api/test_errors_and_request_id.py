import uuid

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


def test_request_id_is_generated_and_echoed(client: TestClient) -> None:
    response = client.get("/health")
    uuid.UUID(response.headers["x-request-id"])


def test_safe_incoming_request_id_is_reused(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "client-trace-1234"})
    assert response.headers["x-request-id"] == "client-trace-1234"


def test_unsafe_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert response.headers["x-request-id"] != "bad id with spaces"
    uuid.UUID(response.headers["x-request-id"])


def test_not_found_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist", headers={"X-Request-ID": "trace-404-abcdef"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "request_id": "trace-404-abcdef"}
    }


def test_validation_error_envelope(client: TestClient, user_headers: dict[str, str]) -> None:
    response = client.get("/documents/not-a-uuid", headers=user_headers)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["path", "document_id"]


def test_unhandled_exception_returns_generic_500(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert response.json()["error"]["code"] == "internal_error"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_cors_allows_only_configured_origins(client: TestClient) -> None:
    allowed = client.options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"
    denied = client.options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in denied.headers
