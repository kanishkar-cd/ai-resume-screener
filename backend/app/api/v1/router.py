from fastapi import APIRouter

from app.api.v1.endpoints import documents, health, parsing, projects, weight_configs, extraction

v1_router = APIRouter()
v1_router.include_router(health.router, prefix="/health", tags=["health"])
v1_router.include_router(projects.router, prefix="/projects", tags=["projects"])
v1_router.include_router(weight_configs.router, prefix="/projects", tags=["projects"])
v1_router.include_router(documents.router, prefix="/documents", tags=["documents"])
v1_router.include_router(parsing.router, prefix="/documents", tags=["documents"])
v1_router.include_router(extraction.router, prefix="/documents", tags=["documents"])