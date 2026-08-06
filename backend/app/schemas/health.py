from app.core.constants import AppEnv
from app.schemas.base import APIModel


class HealthResponse(APIModel):
    status: str
    environment: AppEnv


class ReadinessResponse(APIModel):
    status: str
    database: str
