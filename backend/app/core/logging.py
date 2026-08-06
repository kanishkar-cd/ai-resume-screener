import logging
import logging.config
from typing import Any

import structlog

from app.core.config import Settings
from app.core.constants import AppEnv

SENSITIVE_KEYS = {"authorization", "password", "postgres_password", "token"}


def scrub_sensitive_data(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Redact commonly sensitive fields from structured log events."""
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = "[REDACTED]"
    return event_dict


def setup_logging(settings: Settings) -> None:
    """Configure stdlib and structlog for the active environment."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp")
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        scrub_sensitive_data,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.dev.ConsoleRenderer(colors=True)
        if settings.APP_ENV == AppEnv.DEVELOPMENT
        else structlog.processors.JSONRenderer()
    )
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "structured": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "foreign_pre_chain": shared_processors,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        renderer,
                    ],
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "structured",
                }
            },
            "root": {"handlers": ["default"], "level": "DEBUG" if settings.DEBUG else "INFO"},
        }
    )
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV.value,
    )
