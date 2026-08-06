from fastapi import APIRouter

from app.api.v1.endpoints import health

v1_router = APIRouter()
v1_router.include_router(health.router, prefix="/health", tags=["health"])
