import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog


class AuditLogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        action: str,
        user_id: uuid.UUID | None,
        resource_type: str | None,
        resource_id: str | None,
        details: dict[str, Any],
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        self._session.add(entry)
        self._session.flush()
        return entry

    def list(
        self,
        *,
        offset: int,
        limit: int,
        user_id: uuid.UUID | None = None,
        action: str | None = None,
    ) -> tuple[Sequence[AuditLog], int]:
        conditions = []
        if user_id is not None:
            conditions.append(AuditLog.user_id == user_id)
        if action is not None:
            conditions.append(AuditLog.action == action)
        total = (
            self._session.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
        )
        rows = self._session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return rows, total
