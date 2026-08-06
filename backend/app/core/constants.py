from enum import StrEnum


class AppEnv(StrEnum):
    """Supported application runtime environments."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


SYSTEM_ERROR = "SYSTEM_ERROR"
VALIDATION_ERROR = "VALIDATION_ERROR"
DATABASE_ERROR = "DATABASE_ERROR"
ENTITY_NOT_FOUND = "ENTITY_NOT_FOUND"
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
CONFLICT = "CONFLICT"
