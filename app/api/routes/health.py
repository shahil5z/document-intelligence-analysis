from fastapi import APIRouter

from app.schemas.health import LivenessResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Cheap check that the process is serving requests. Touches no dependencies.",
)
def liveness() -> LivenessResponse:
    return LivenessResponse()
