from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.base import APIModel


class ErrorDetail(APIModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    correlation_id: str


class ErrorResponsePayload(APIModel):
    error: ErrorDetail
