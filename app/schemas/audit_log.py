import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str = Field(examples=["document.uploaded"])
    resource_type: str | None
    resource_id: str | None
    metadata: dict[str, Any] = Field(validation_alias="details")
    created_at: datetime
