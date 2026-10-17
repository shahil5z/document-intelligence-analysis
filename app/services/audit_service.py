import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.core.request_context import get_request_id
from app.db.models import AuditLog
from app.db.repositories.audit_logs import AuditLogRepository
from app.domain.enums import AuditAction, ResourceType


class AuditService:
    """Writes audit entries inside the caller's transaction (the caller commits)."""

    def __init__(self, session: Session) -> None:
        self._repo = AuditLogRepository(session)

    def record(
        self,
        action: AuditAction,
        *,
        user_id: uuid.UUID | None,
        resource_type: ResourceType | None = None,
        resource_id: uuid.UUID | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        payload = dict(details or {})
        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        return self._repo.add(
            action=action.value,
            user_id=user_id,
            resource_type=resource_type.value if resource_type else None,
            resource_id=str(resource_id) if resource_id is not None else None,
            details=payload,
        )

    def list(
        self,
        *,
        offset: int,
        limit: int,
        user_id: uuid.UUID | None = None,
        action: str | None = None,
    ) -> tuple[Sequence[AuditLog], int]:
        return self._repo.list(offset=offset, limit=limit, user_id=user_id, action=action)
