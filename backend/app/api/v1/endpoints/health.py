import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import ConfigDependency, DatabaseDependency
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/liveness", response_model=HealthResponse)
async def liveness(settings: ConfigDependency) -> HealthResponse:
    """Report whether the API process is alive."""
    return HealthResponse(status="ok", environment=settings.APP_ENV)


@router.get("/readiness", response_model=ReadinessResponse)
async def readiness(db: DatabaseDependency) -> ReadinessResponse:
    """Report whether PostgreSQL is reachable."""
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Database readiness probe failed", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        ) from exc
    logger.info("Database readiness probe successful")
    return ReadinessResponse(status="ok", database="connected")
