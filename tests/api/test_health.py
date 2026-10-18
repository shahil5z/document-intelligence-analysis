import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.session import get_engine
from app.services.health_service import HealthService, get_health_service


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
    assert response.json()["status"] == "ready"
