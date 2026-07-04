from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from canterlot.exceptions.base import ErrorCode


class ErrorDetail(BaseModel):
    error_code: ErrorCode = Field(
        ...,
        description="A unique, stable code for machine consumption (e.g., 'BOOK_NOT_FOUND').",
    )
    message: str = Field(
        ...,
        description="A human-readable description of the error suitable for logs or debugging.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="The exact UTC timestamp when the error occurred."
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata or fields to provide extra context to the frontend.",
    )


class ErrorResponseModel(BaseModel):
    error: ErrorDetail
