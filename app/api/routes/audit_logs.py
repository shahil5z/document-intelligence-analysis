from fastapi import APIRouter

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.pagination import Pagination
from app.api.dependencies.services import AuditServiceDep
from app.api.responses import error_responses
from app.schemas.audit_log import AuditLogRead
from app.schemas.common import Page

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get(
    "/me",
    response_model=Page[AuditLogRead],
    summary="My audit log entries",
    responses=error_responses(401, 422),
)
def my_audit_logs(
    user: CurrentUser, audit: AuditServiceDep, pagination: Pagination
) -> Page[AuditLogRead]:
    rows, total = audit.list(offset=pagination.offset, limit=pagination.page_size, user_id=user.id)
    return Page[AuditLogRead](
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        items=[AuditLogRead.model_validate(row) for row in rows],
    )
