import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.auth import AdminUser
from app.api.dependencies.pagination import Pagination
from app.api.dependencies.services import AuditServiceDep, UserServiceDep
from app.api.responses import error_responses
from app.schemas.audit_log import AuditLogRead
from app.schemas.common import Page
from app.schemas.user import UserRead

router = APIRouter(prefix="/admin", tags=["admin"], responses=error_responses(401, 403, 422))


@router.get("/users", response_model=Page[UserRead], summary="List all users (admin)")
def list_users(_: AdminUser, users: UserServiceDep, pagination: Pagination) -> Page[UserRead]:
    rows, total = users.list_users(offset=pagination.offset, limit=pagination.page_size)
    return Page[UserRead](
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        items=[UserRead.model_validate(row) for row in rows],
    )


@router.get(
    "/audit-logs", response_model=Page[AuditLogRead], summary="List audit log entries (admin)"
)
def list_audit_logs(
    _: AdminUser,
    audit: AuditServiceDep,
    pagination: Pagination,
    user_id: Annotated[uuid.UUID | None, Query(description="Filter by acting user.")] = None,
    action: Annotated[
        str | None, Query(max_length=64, description="Filter by action, e.g. `user.login`.")
    ] = None,
) -> Page[AuditLogRead]:
    rows, total = audit.list(
        offset=pagination.offset, limit=pagination.page_size, user_id=user_id, action=action
    )
    return Page[AuditLogRead](
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        items=[AuditLogRead.model_validate(row) for row in rows],
    )
