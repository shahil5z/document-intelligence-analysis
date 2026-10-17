from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


class Page[T](BaseModel):
    total: int = Field(description="Total number of items across all pages.")
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=MAX_PAGE_SIZE)
    items: list[T]


class ErrorDetail(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Document not found"])
    request_id: str | None = Field(default=None, examples=["5f0c6c1e-2b8f-4a59-9c39-0e8f4a8b1a77"])
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {
                    "code": "not_found",
                    "message": "Document not found",
                    "request_id": "5f0c6c1e-2b8f-4a59-9c39-0e8f4a8b1a77",
                }
            }
        }
    )

    error: ErrorDetail
