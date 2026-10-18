from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.user import DemoStatus

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "jane@example.com", "password": "correct-horse-battery-staple"}
        }
    )

    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "jane@example.com", "password": "correct-horse-battery-staple"}
        }
    )

    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class UploadTokenResponse(BaseModel):
    upload_token: str = Field(description="Bearer token accepted only by POST /documents.")
    token_type: str = "bearer"  # noqa: S105  (OAuth2 token type, not a secret)
    expires_in: int = Field(description="Token lifetime in seconds.", examples=[300])


class DemoSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105  (OAuth2 token type, not a secret)
    expires_in: int = Field(description="Token lifetime in seconds (at most 2 hours).")
    demo: DemoStatus


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105  (OAuth2 token type, not a secret)
    expires_in: int = Field(description="Token lifetime in seconds.", examples=[1800])
