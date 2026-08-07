from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.scoring_repository import ScoringRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.scoring import CandidateScoreResponse, ProjectScoringResponse, ProjectScoresResponse
from app.services.scoring_service import ScoringEngineFacade

router = APIRouter()


def get_scoring_facade(db: DatabaseDependency) -> ScoringEngineFacade:
    return ScoringEngineFacade(
        ProjectRepository(db), DocumentRepository(db), NormalizationRepository(db),
        ExtractionRepository(db), WeightConfigRepository(db), ScoringRepository(db),
    )


ScoringDependency = Annotated[ScoringEngineFacade, Depends(get_scoring_facade)]
ERRORS = {
    400: {"model": ErrorResponsePayload, "description": "Required normalized input or weight configuration is missing."},
    404: {"model": ErrorResponsePayload, "description": "Project, document, or score not found."},
    422: {"model": ErrorResponsePayload, "description": "Document does not belong to the project."},
    500: {"model": ErrorResponsePayload, "description": "Scoring execution failed."},
}


@router.post("/projects/{project_id}/score", response_model=ProjectScoringResponse, summary="Score all project resumes", description="Run both deterministic scoring engines for every active resume in the project.", responses=ERRORS)
async def score_project(project_id: UUID, service: ScoringDependency) -> ProjectScoringResponse:
    return ProjectScoringResponse(data=await service.score_project(project_id))


@router.post("/projects/{project_id}/documents/{document_id}/score", response_model=CandidateScoreResponse, summary="Score one project resume", description="Run both deterministic scoring engines for one project-owned resume.", responses=ERRORS)
async def score_document(project_id: UUID, document_id: UUID, service: ScoringDependency) -> CandidateScoreResponse:
    return CandidateScoreResponse(data=await service.score_document(project_id, document_id))


@router.get("/projects/{project_id}/scores", response_model=ProjectScoresResponse, summary="Get project candidate scores", responses=ERRORS)
async def get_project_scores(project_id: UUID, service: ScoringDependency) -> ProjectScoresResponse:
    return ProjectScoresResponse(data=await service.get_project_scores(project_id))


@router.get("/documents/{document_id}/score", response_model=CandidateScoreResponse, summary="Get candidate score breakdown", responses=ERRORS)
async def get_document_score(document_id: UUID, service: ScoringDependency) -> CandidateScoreResponse:
    return CandidateScoreResponse(data=await service.get_document_score(document_id))
