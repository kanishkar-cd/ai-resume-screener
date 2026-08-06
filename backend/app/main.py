from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import engine
from app.middlewares.correlation import RequestCorrelationIdMiddleware
from app.middlewares.error_handler import register_exception_handlers
from app.middlewares.logging import RequestTimingLoggingMiddleware
from app.middlewares.security_headers import SecurityHeadersMiddleware

settings = get_settings()
setup_logging(settings)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Check infrastructure at startup and release the pool at shutdown."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        logger.info("Database startup readiness check successful")
    except Exception as exc:
        logger.warning(
            "Database startup readiness check failed",
            error_type=type(exc).__name__,
        )
    logger.info("Application startup complete")
    yield
    await engine.dispose()
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI ASGI application."""
    application = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        docs_url="/docs",
        lifespan=lifespan,
    )

    # Starlette wraps middleware in reverse registration order. This produces
    # Correlation -> Security -> CORS -> Timing -> GZip -> Router on requests.
    application.add_middleware(GZipMiddleware, minimum_size=1000)
    application.add_middleware(RequestTimingLoggingMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RequestCorrelationIdMiddleware)

    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.API_V1_STR)
    return application


app = create_app()
