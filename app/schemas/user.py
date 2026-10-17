import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import UserRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
