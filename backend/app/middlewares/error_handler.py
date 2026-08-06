from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.constants import SYSTEM_ERROR, VALIDATION_ERROR
from app.core.exceptions import AppException
from app.schemas.error import ErrorDetail, ErrorResponsePayload

logger = structlog.get_logger(__name__)


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any],
) -> JSONResponse:
    payload = ErrorResponsePayload(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details,
            timestamp=datetime.now(UTC),
            correlation_id=_correlation_id(request),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return _error_response(
        request,
        status_code=exc.status_code,
        code=exc.error_code,
        message=exc.message,
        details=exc.details,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_response(
        request,
        status_code=422,
        code=VALIDATION_ERROR,
        message="Request validation failed.",
        details={"errors": exc.errors()},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application exception", error_type=type(exc).__name__)
    return _error_response(
        request,
        status_code=500,
        code=SYSTEM_ERROR,
        message="An internal server error occurred.",
        details={},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the application's uniform exception response handlers."""
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
