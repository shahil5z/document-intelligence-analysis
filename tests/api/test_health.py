import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.session import get_engine
from app.services.health_service import (
    HealthService,
    evaluate_pgvector_version,
    get_health_service,
)


@pytest.mark.parametrize("path", ["/health", "/health/live"])
def test_liveness(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_503_when_redis_rejects_credentials(
    app: FastAPI, client: TestClient
) -> None:
    redis_url = os.environ.get("TEST_REDIS_URL")
    if not redis_url or "@" not in redis_url:
        pytest.skip("TEST_REDIS_URL with a password not set")
    scheme, rest = redis_url.split("://", 1)
    wrong = f"{scheme}://:wrong-password@{rest.split('@', 1)[1]}"
    app.dependency_overrides[get_health_service] = lambda: HealthService(get_engine(), wrong)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"]["status"] == "error"
    assert "wrong-password" not in response.text


def test_readiness_reports_503_when_redis_is_unreachable(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        get_engine(), "redis://127.0.0.1:1/0"
    )
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"] == {"status": "error", "error": "redis unavailable"}


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="TEST_REDIS_URL not set")
def test_readiness_ok_with_real_redis(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        get_engine(), os.environ["TEST_REDIS_URL"]
    )
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["pgvector"] == {"status": "ok", "error": None}


def test_readiness_checks_the_installed_pgvector_version(app: FastAPI, client: TestClient) -> None:
    del app
    check = client.get("/health/ready").json()["checks"]["pgvector"]
    # The test database runs the migrations, so the extension is installed (>= 0.5.0).
    assert check["status"] == "ok"


@pytest.mark.parametrize(
    ("version", "status", "error"),
    [
        (None, "error", "pgvector extension is not installed"),
        ("0.4.4", "error", "pgvector >= 0.5.0 is required"),
        ("0.5.0", "ok", None),
        ("0.6.2", "ok", None),
        ("0.8.0", "ok", None),
        ("0.8.7", "ok", None),
    ],
)
def test_pgvector_version_policy(version: str | None, status: str, error: str | None) -> None:
    check = evaluate_pgvector_version(version)
    assert (check.status, check.error) == (status, error)
