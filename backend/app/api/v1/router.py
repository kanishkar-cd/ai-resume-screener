from fastapi import APIRouter

from app.api.v1.endpoints import (
    documents, extraction, health, normalization, parsing, project_documents, projects,
    weight_config,
    scoring,
    ranking,
    reporting,
)

v1_router = APIRouter()
v1_router.include_router(health.router, prefix="/health", tags=["health"])
v1_router.include_router(projects.router, prefix="/projects", tags=["projects"])
v1_router.include_router(weight_config.router, prefix="/projects", tags=["weight configuration"])
v1_router.include_router(documents.router, prefix="/documents", tags=["documents"])
v1_router.include_router(parsing.router, prefix="/documents", tags=["parsing"])
v1_router.include_router(extraction.router, prefix="/documents", tags=["extraction"])
v1_router.include_router(normalization.router, prefix="/documents", tags=["normalization"])
v1_router.include_router(project_documents.router, tags=["project documents"])
v1_router.include_router(scoring.router, tags=["scoring"])
v1_router.include_router(ranking.router, tags=["ranking"])
v1_router.include_router(reporting.router, tags=["reporting"])
