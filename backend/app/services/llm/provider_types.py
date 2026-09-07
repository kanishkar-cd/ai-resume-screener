from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

from app.schemas.matching import Evidence, LLMVerdictBatch, MatchVerdict, Requirement


class ProviderStatus(str, Enum):
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    PAYMENT_REQUIRED = "payment_required"
    AUTH_FAILED = "auth_failed"
    MODEL_NOT_FOUND = "model_not_found"
    SERVER_ERROR = "server_error"
    INVALID_RESPONSE = "invalid_response"
    CIRCUIT_OPEN = "circuit_open"
    DISABLED = "disabled"
    UNKNOWN_ERROR = "unknown_error"

    @property
    def is_success(self) -> bool:
        return self == ProviderStatus.SUCCESS

    @property
    def is_rate_limit_or_quota(self) -> bool:
        return self in {
            ProviderStatus.RATE_LIMITED,
            ProviderStatus.BUDGET_EXHAUSTED,
        }

    @property
    def is_permanent(self) -> bool:
        return self in {
            ProviderStatus.PAYMENT_REQUIRED,
            ProviderStatus.AUTH_FAILED,
            ProviderStatus.MODEL_NOT_FOUND,
        }


class LLMRequest(BaseModel):
    requirements: list[Requirement]
    evidence: list[Evidence]
    allowed_evidence: dict[str, set[str]] | None = None
    resume_id: str = "default_resume"
    estimated_tokens: int = 0


class ProviderResult(BaseModel):
    provider: str
    status: ProviderStatus
    data: LLMVerdictBatch | None = None
    verdicts: list[MatchVerdict] = Field(default_factory=list)
    raw_response: str | None = None
    usage: dict[str, int] = Field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    latency_ms: float = 0.0
    error_message: str | None = None
    status_code: int | None = None
    is_retryable: bool = False
