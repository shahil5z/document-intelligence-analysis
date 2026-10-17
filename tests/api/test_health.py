import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.session import get_engine
from app.services.health_service import HealthService, get_health_service


def test_liveness(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
