from fastapi import APIRouter, Response

from app.core.metrics import render_latest

router = APIRouter(tags=["health"])


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    description=(
        "Prometheus text exposition. Labels are low-cardinality (route templates, status "
        "codes, fixed outcome names). Do not expose this endpoint publicly; scrape it from "
        "the internal network (see docs/observability.md)."
    ),
    include_in_schema=False,
)
def metrics() -> Response:
    payload, content_type = render_latest()
    return Response(content=payload, media_type=content_type)
