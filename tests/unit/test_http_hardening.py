"""HTTP-level hardening without a database: body limits, rate limits, security headers,
API docs exposure, metrics labels and error envelopes.

Services that would touch PostgreSQL are replaced through FastAPI dependency overrides;
the routes, middleware, dependencies and exception handlers are the real ones.
"""

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.api.dependencies.auth import get_current_active_user
from app.api.dependencies.services import get_auth_service, get_search_service
from app.core.config import Environment, Settings, get_settings
from app.core.errors import AuthenticationError, ConflictError
from app.domain.enums import SearchMode
from app.main import create_app
from app.services.search_service import SearchResult


def _settings(**update: Any) -> Settings:
    return get_settings().model_copy(update=update)


class _FakeAuth:
    def __init__(self) -> None:
        self.logins: list[str] = []

    def register(self, *, email: str, password: str) -> None:
        del password
        raise ConflictError(f"exists: {email[:0]}")

    def login(self, *, email: str, password: str) -> None:
        del password
        self.logins.append(email)
        raise AuthenticationError("Incorrect email or password")


class _FakeSearch:
    def search(self, **_: Any) -> SearchResult:
        return SearchResult(mode=SearchMode.KEYWORD, results=[], reranked=False)


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def fake_auth() -> _FakeAuth:
    return _FakeAuth()


def _app(fake_auth: _FakeAuth | None = None, **settings_update: Any) -> FastAPI:
    app = create_app(_settings(**settings_update))
    if fake_auth is not None:
        app.dependency_overrides[get_auth_service] = lambda: fake_auth
    return app


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# --- request body limits -------------------------------------------------------------


def test_declared_oversized_json_body_is_rejected_before_the_route(fake_auth: _FakeAuth) -> None:
    app = _app(fake_auth, max_request_body_bytes=1024)
    with _client(app) as client:
        response = client.post(
            "/auth/login",
            content=b"{" + b" " * 4000 + b"}",
            headers={"Content-Type": "application/json", "X-Request-ID": "trace-413-abcdef"},
        )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "payload_too_large"
    assert error["request_id"] == "trace-413-abcdef"
    assert response.headers["x-request-id"] == "trace-413-abcdef"
    assert fake_auth.logins == []


def test_chunked_body_without_length_is_cut_off(fake_auth: _FakeAuth) -> None:
    app = _app(fake_auth, max_request_body_bytes=1024)

    def body() -> Iterator[bytes]:
        for _ in range(10):
            yield b"x" * 512

    with _client(app) as client:
        response = client.post(
            "/auth/login", content=body(), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert fake_auth.logins == []


def test_upload_route_gets_the_upload_limit_and_rejects_streamed_overflow() -> None:
    # MAX_UPLOAD_SIZE_BYTES is 64 KiB in the test environment (tests/conftest.py).
    app = _app(upload_body_overhead_bytes=1024)
    boundary = "dipboundary"

    def multipart() -> Iterator[bytes]:
        yield (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="big.txt"\r\nContent-Type: text/plain\r\n\r\n'
        ).encode()
        for _ in range(100):
            yield b"a" * 4096
        yield f"\r\n--{boundary}--\r\n".encode()

    with _client(app) as client:
        response = client.post(
            "/documents",
            content=multipart(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_small_bodies_pass_through(fake_auth: _FakeAuth) -> None:
    with _client(_app(fake_auth)) as client:
        response = client.post("/auth/login", json={"email": "a@example.com", "password": "x" * 12})
    assert response.status_code == 401
    assert fake_auth.logins == ["a@example.com"]


# --- rate limiting -------------------------------------------------------------------


def _limited(fake_auth: _FakeAuth, **update: Any) -> FastAPI:
    return _app(fake_auth, rate_limit_enabled=True, rate_limit_backend="memory", **update)


def test_register_is_limited_per_ip_with_retry_after(fake_auth: _FakeAuth) -> None:
    app = _limited(fake_auth, rate_limit_register="2/minute")
    body = {"email": "new@example.com", "password": "a-long-enough-password"}
    with _client(app) as client:
        statuses = [client.post("/auth/register", json=body).status_code for _ in range(3)]
        blocked = client.post("/auth/register", json=body)
    assert statuses == [409, 409, 429]
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.headers["x-request-id"] == blocked.json()["error"]["request_id"]


def test_login_is_limited_per_email_independently_of_ip(fake_auth: _FakeAuth) -> None:
    app = _limited(fake_auth, rate_limit_login="100/minute", rate_limit_login_per_email="2/minute")
    before = _sample("dip_rate_limited_total", {"scope": "login_per_email"})
    with _client(app) as client:
        victim = [
            client.post(
                "/auth/login", json={"email": "Victim@Example.com", "password": "x" * 12}
            ).status_code
            for _ in range(3)
        ]
        other = client.post("/auth/login", json={"email": "other@example.com", "password": "y"})
        form = client.post(
            "/auth/token", data={"username": "victim@example.com", "password": "x" * 12}
        )
    # The e-mail is normalised, so case variants share one bucket (JSON and form login).
    assert victim == [401, 401, 429]
    assert other.status_code == 401
    assert form.status_code == 429
    assert _sample("dip_rate_limited_total", {"scope": "login_per_email"}) == before + 2


def test_authenticated_limits_are_per_user(fake_auth: _FakeAuth) -> None:
    app = _limited(fake_auth, rate_limit_search="2/minute")
    users = {"a": SimpleNamespace(id=uuid.uuid4()), "b": SimpleNamespace(id=uuid.uuid4())}
    current = {"user": users["a"]}
    app.dependency_overrides[get_current_active_user] = lambda: current["user"]
    app.dependency_overrides[get_search_service] = _FakeSearch
    with _client(app) as client:
        first = [client.post("/search", json={"query": "q"}).status_code for _ in range(3)]
        current["user"] = users["b"]
        second = client.post("/search", json={"query": "q"}).status_code
    assert first == [200, 200, 429]
    assert second == 200


def test_rate_limits_disabled_means_no_429(fake_auth: _FakeAuth) -> None:
    app = _app(fake_auth, rate_limit_enabled=False, rate_limit_register="1/minute")
    body = {"email": "new@example.com", "password": "a-long-enough-password"}
    with _client(app) as client:
        statuses = {client.post("/auth/register", json=body).status_code for _ in range(5)}
    assert statuses == {409}


# --- headers, docs, CORS -------------------------------------------------------------


def test_security_headers_are_set_and_hsts_only_in_production() -> None:
    with _client(_app()) as client:
        dev = client.get("/health")
    assert dev.headers["x-content-type-options"] == "nosniff"
    assert dev.headers["x-frame-options"] == "DENY"
    assert dev.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in dev.headers
    with _client(_app(app_env=Environment.PRODUCTION)) as client:
        prod = client.get("/health")
    assert prod.headers["strict-transport-security"].startswith("max-age=")


def test_api_docs_are_off_in_production_unless_enabled() -> None:
    with _client(_app()) as client:
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200
    with _client(_app(app_env=Environment.PRODUCTION)) as client:
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/docs").status_code == 404
    with _client(_app(app_env=Environment.PRODUCTION, api_docs_enabled=True)) as client:
        assert client.get("/openapi.json").status_code == 200


def test_cors_preflight_for_disallowed_origin_gets_no_grant() -> None:
    with _client(_app(cors_allowed_origins=["https://app.example.com"])) as client:
        allowed = client.options(
            "/search",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        denied = client.options(
            "/search",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
    assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
    assert "access-control-allow-credentials" not in allowed.headers
    assert "access-control-allow-origin" not in denied.headers
    assert "x-request-id" in denied.headers


# --- metrics -------------------------------------------------------------------------


def test_metrics_use_route_templates_not_raw_paths() -> None:
    document_id = uuid.uuid4()
    with _client(_app()) as client:
        assert client.get(f"/documents/{document_id}").status_code == 401
        assert client.get("/no/such/path").status_code == 404
        metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    text = metrics.text
    assert 'route="/documents/{document_id}"' in text
    assert 'route="unmatched"' in text
    assert str(document_id) not in text
    assert "/no/such/path" not in text
    assert "dip_http_request_duration_seconds_bucket" in text


def test_metrics_endpoint_can_be_disabled() -> None:
    with _client(_app(metrics_enabled=False)) as client:
        assert client.get("/metrics").status_code == 404


def test_internal_errors_do_not_leak_details() -> None:
    app = _app()

    @app.get("/explode")
    def explode() -> None:
        raise ValueError("password=hunter2 at /srv/secret/path")

    with _client(app) as client:
        response = client.get("/explode")
    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert "/srv/secret" not in response.text
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "Internal server error",
        "request_id": response.headers["x-request-id"],
    }
