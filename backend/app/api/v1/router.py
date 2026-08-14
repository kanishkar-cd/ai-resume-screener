from fastapi import APIRouter

from app.api.v1.endpoints import (
    documents,
    extraction,
    health,
    normalization,
    parsing,
    project_documents,
    projects,
    ranking,
    reporting,
    scoring,
)

v1_router = APIRouter()
v1_router.include_router(health.router, prefix="/health", tags=["health"])
v1_router.include_router(projects.router, prefix="/projects", tags=["projects"])
v1_router.include_router(project_documents.router, tags=["projects"])
v1_router.include_router(documents.router, prefix="/documents", tags=["documents"])
v1_router.include_router(parsing.router, prefix="/documents", tags=["documents"])
v1_router.include_router(extraction.router, prefix="/documents", tags=["documents"])
v1_router.include_router(normalization.router, prefix="/documents", tags=["documents"])
v1_router.include_router(scoring.router, tags=["scoring"])
v1_router.include_router(ranking.router, tags=["ranking"])
v1_router.include_router(reporting.router, tags=["reporting"])