"""HTTP-level hardening without a database: body limits, rate limits, security headers,
API docs exposure, metrics labels and error envelopes.

Services that would touch PostgreSQL are replaced through FastAPI dependency overrides;
the routes, middleware, dependencies and exception handlers are the real ones.
"""

import uuid
from collections.abc import Iterator, MutableMapping
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from pydantic import SecretStr

from app.api.dependencies.auth import get_current_active_user
from app.api.dependencies.services import get_auth_service, get_search_service
from app.core.config import Environment, Settings, SettingsError, get_settings, load_settings
from app.core.errors import AuthenticationError, ConflictError
from app.domain.enums import SearchMode, UserRole
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


def test_daily_window_applies_after_the_per_minute_one(fake_auth: _FakeAuth) -> None:
    app = _limited(fake_auth, rate_limit_register="100/minute", rate_limit_register_daily="2/day")
    body = {"email": "new@example.com", "password": "a-long-enough-password"}
    before = _sample("dip_rate_limited_total", {"scope": "register_daily"})
    with _client(app) as client:
        statuses = [client.post("/auth/register", json=body).status_code for _ in range(3)]
        blocked = client.post("/auth/register", json=body)
    assert statuses == [409, 409, 429]
    # Retry-After reflects the daily window (the rest of the UTC day), not a minute.
    assert int(blocked.headers["retry-after"]) >= 1
    assert _sample("dip_rate_limited_total", {"scope": "register_daily"}) == before + 2


def test_upload_token_is_rate_limited_per_user(fake_auth: _FakeAuth) -> None:
    app = _limited(fake_auth, rate_limit_upload_token="2/minute")
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.USER)
    app.dependency_overrides[get_current_active_user] = lambda: user
    with _client(app) as client:
        statuses = [client.post("/auth/upload-token").status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


CLIENT_SECRET = "s" * 32


def _register_twice(app: FastAPI, headers: list[dict[str, str]]) -> list[int]:
    body = {"email": "new@example.com", "password": "a-long-enough-password"}
    with _client(app) as client:
        return [client.post("/auth/register", json=body, headers=h).status_code for h in headers]


def test_trusted_bff_can_name_the_client_ip(fake_auth: _FakeAuth) -> None:
    app = _limited(
        fake_auth,
        rate_limit_register="1/minute",
        client_ip_header_secret=SecretStr(CLIENT_SECRET),
    )
    trusted = {"X-DIP-Client-Secret": CLIENT_SECRET}
    statuses = _register_twice(
        app,
        [
            {**trusted, "X-DIP-Client-IP": "198.51.100.1"},
            {**trusted, "X-DIP-Client-IP": "198.51.100.2"},
            {**trusted, "X-DIP-Client-IP": "198.51.100.1"},
        ],
    )
    assert statuses == [409, 409, 429]


@pytest.mark.parametrize(
    "headers",
    [
        {"X-DIP-Client-IP": "198.51.100.9"},
        {"X-DIP-Client-Secret": "wrong" * 8, "X-DIP-Client-IP": "198.51.100.9"},
        {"X-DIP-Client-Secret": CLIENT_SECRET, "X-DIP-Client-IP": "not-an-ip"},
    ],
)
def test_untrusted_client_ip_headers_are_ignored(
    fake_auth: _FakeAuth, headers: dict[str, str]
) -> None:
    app = _limited(
        fake_auth,
        rate_limit_register="1/minute",
        client_ip_header_secret=SecretStr(CLIENT_SECRET),
    )
    assert _register_twice(app, [{}, headers]) == [409, 429]


def test_client_ip_header_is_ignored_without_a_secret(fake_auth: _FakeAuth) -> None:
    app = _limited(fake_auth, rate_limit_register="1/minute")
    headers = {"X-DIP-Client-Secret": "", "X-DIP-Client-IP": "198.51.100.3"}
    assert _register_twice(app, [{}, headers]) == [409, 429]


def test_short_client_ip_secret_is_rejected() -> None:
    with pytest.raises(SettingsError, match="CLIENT_IP_HEADER_SECRET"):
        load_settings(
            _env_file=None, app_env="test", jwt_secret_key="k" * 40, client_ip_header_secret="x"
        )


def test_public_demo_defaults_are_conservative() -> None:
    # Class defaults (a local .env may override them).
    defaults = {name: field.default for name, field in Settings.model_fields.items()}
    assert defaults["rate_limit_demo"] == "3/day"
    assert defaults["rate_limit_ask"] == "10/minute"
    assert defaults["rate_limit_ask_daily"] == "200/day"
    assert defaults["rate_limit_upload_daily"] == "100/day"
    assert defaults["demo_max_questions"] == 3
    assert defaults["demo_max_uploads"] == 1
    assert defaults["demo_max_upload_bytes"] == 5 * 1024 * 1024


def test_rate_limits_disabled_means_no_429(fake_auth: _FakeAuth) -> None:
    app = _app(fake_auth, rate_limit_enabled=False, rate_limit_register="1/minute")
    body = {"email": "new@example.com", "password": "a-long-enough-password"}
    with _client(app) as client:
        statuses = {client.post("/auth/register", json=body).status_code for _ in range(5)}
    assert statuses == {409}


def _redis_down(fake_auth: _FakeAuth) -> FastAPI:
    """Redis backend pointed at a closed port: every limiter call fails."""
    return _app(
        fake_auth,
        rate_limit_enabled=True,
        rate_limit_backend="redis",
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
    )


@pytest.mark.parametrize(
    ("path", "kwargs", "scope"),
    [
        ("/auth/login", {"json": {"email": "a@example.com", "password": "x" * 12}}, "login"),
        ("/auth/token", {"data": {"username": "a@example.com", "password": "x" * 12}}, "login"),
        (
            "/auth/register",
            {"json": {"email": "a@example.com", "password": "a-long-enough-password"}},
            "register",
        ),
        ("/auth/demo", {}, "demo"),
    ],
)
def test_credential_endpoints_fail_closed_when_rate_limiter_is_down(
    fake_auth: _FakeAuth, path: str, kwargs: dict[str, Any], scope: str
) -> None:
    before = _sample("dip_rate_limiter_errors_total", {"scope": scope, "decision": "fail_closed"})
    with _client(_redis_down(fake_auth)) as client:
        response = client.post(path, **kwargs)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert int(response.headers["retry-after"]) >= 1
    assert "127.0.0.1" not in response.text
    # The credentials were never checked.
    assert fake_auth.logins == []
    after = _sample("dip_rate_limiter_errors_total", {"scope": scope, "decision": "fail_closed"})
    assert after == before + 1


def test_authenticated_endpoints_fail_open_when_rate_limiter_is_down(
    fake_auth: _FakeAuth, capsys: pytest.CaptureFixture[str]
) -> None:
    app = _redis_down(fake_auth)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[get_search_service] = _FakeSearch
    before = _sample("dip_rate_limiter_errors_total", {"scope": "search", "decision": "fail_open"})
    with _client(app) as client:
        statuses = [client.post("/search", json={"query": "q"}).status_code for _ in range(2)]
    assert statuses == [200, 200]
    after = _sample("dip_rate_limiter_errors_total", {"scope": "search", "decision": "fail_open"})
    assert after == before + 2
    logged = capsys.readouterr()
    assert '"decision": "fail_open"' in logged.out + logged.err


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


def test_declared_oversized_upload_is_rejected_without_reading_the_body() -> None:
    """Content-Length above the limit -> 413 before a single body chunk is received."""
    import asyncio  # noqa: PLC0415

    from app.core.middleware import BodySizeLimitMiddleware  # noqa: PLC0415

    app_called = False
    receive_calls = 0
    sent: list[dict[str, Any]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        nonlocal app_called
        app_called = True

    async def receive() -> dict[str, Any]:
        nonlocal receive_calls
        receive_calls += 1
        return {"type": "http.request", "body": b"x" * 1024, "more_body": True}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(dict(message))

    middleware = BodySizeLimitMiddleware(inner, default_limit=1024, upload_limit=4096)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/documents",
        "headers": [(b"content-length", b"10485760000")],
    }
    asyncio.run(middleware(scope, receive, send))
    assert not app_called
    assert receive_calls == 0
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
