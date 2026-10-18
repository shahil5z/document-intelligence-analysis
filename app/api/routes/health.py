import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.schemas.health import DependencyCheck, LivenessResponse, ReadinessResponse
from app.services.health_service import HealthService, get_health_service

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get(
    "",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Cheap check that the process is serving requests. Touches no dependencies.",
)
def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe (alias)",
    description="Same as `GET /health`, for orchestrators that expect a `/live` path.",
)
def liveness_live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description=(
        "Runs `SELECT 1` on PostgreSQL, checks that the pgvector extension is installed in "
        "version 0.5.0 or newer, and sends `PING` to Redis. Returns 503 if any check fails."
    ),
    responses={503: {"model": ReadinessResponse, "description": "A dependency is unavailable"}},
)
def readiness(
    health: Annotated[HealthService, Depends(get_health_service)],
) -> JSONResponse:
    checks: dict[str, DependencyCheck] = {
        "database": health.check_database(),
        "pgvector": health.check_pgvector(),
        "redis": health.check_redis(),
    }
    ready = all(check.status == "ok" for check in checks.values())
    if not ready:
        logger.warning(
            "health.not_ready", extra={"checks": {k: v.status for k, v in checks.items()}}
        )
    body = ReadinessResponse(status="ready" if ready else "not_ready", checks=checks)
    return JSONResponse(status_code=200 if ready else 503, content=body.model_dump(mode="json"))
