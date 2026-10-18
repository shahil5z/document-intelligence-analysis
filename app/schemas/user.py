import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import UserRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
    is_demo: bool = False
    demo: "DemoStatus | None" = Field(
        default=None, description="Usage and limits; only for demo accounts (`/auth/me`)."
    )


class DemoStatus(BaseModel):
    questions_used: int
    questions_limit: int
    questions_remaining: int
    uploads_used: int
    uploads_limit: int
    max_upload_bytes: int
    allowed_extensions: list[str]
    expires_at: datetime | None


UserRead.model_rebuild()
