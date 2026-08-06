from typing import Any

from app.core.constants import (
    CONFLICT,
    ENTITY_NOT_FOUND,
    FORBIDDEN,
    SYSTEM_ERROR,
    UNAUTHORIZED,
    VALIDATION_ERROR,
)


class AppException(Exception):
    """Base exception carrying the public API error contract."""

    status_code = 500
    error_code = SYSTEM_ERROR
    default_message = "An application error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class NotFoundException(AppException):
    status_code = 404
    error_code = ENTITY_NOT_FOUND
    default_message = "The requested resource was not found."


class UnauthorizedException(AppException):
    status_code = 401
    error_code = UNAUTHORIZED
    default_message = "Authentication is required."


class ForbiddenException(AppException):
    status_code = 403
    error_code = FORBIDDEN
    default_message = "Access is forbidden."


class ValidationException(AppException):
    status_code = 422
    error_code = VALIDATION_ERROR
    default_message = "Request validation failed."


class ConflictException(AppException):
    status_code = 409
    error_code = CONFLICT
    default_message = "The request conflicts with the current state."


class InternalServerException(AppException):
    status_code = 500
    error_code = SYSTEM_ERROR
    default_message = "An internal server error occurred."
