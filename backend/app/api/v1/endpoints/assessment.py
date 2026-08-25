from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, status

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.assessment import AssessmentHandoffRequest, AssessmentHandoffResponse
from app.schemas.error import ErrorResponsePayload
from app.services.assessment_service import AssessmentService

router = APIRouter()


def get_assessment_service(db: DatabaseDependency) -> AssessmentService:
    return AssessmentService(
        ProjectRepository(db),
        DocumentRepository(db),
        ExtractionRepository(db),
        ScoringRepository(db),
    )



AssessmentDependency = Annotated[AssessmentService, Depends(get_assessment_service)]

ERRORS = {
    400: {"model": ErrorResponsePayload, "description": "Invalid handoff payload."},
    404: {"model": ErrorResponsePayload, "description": "Project or candidate document not found."},
    422: {"model": ErrorResponsePayload, "description": "Validation error."},
    500: {"model": ErrorResponsePayload, "description": "Internal server error."},
    502: {"model": ErrorResponsePayload, "description": "CD-Recruit integration service failed."},
}


@router.post(
    "/projects/{project_id}/assessment/handoff",
    response_model=AssessmentHandoffResponse,
    status_code=status.HTTP_200_OK,
    summary="Hand off shortlisted candidates to CD-Recruit technical assessment",
    description="Loads candidate details and dispatches an assessment invitation request to CD-Recruit.",
    responses=ERRORS,
)
async def handoff_assessment(
    project_id: UUID,
    payload: AssessmentHandoffRequest,
    service: AssessmentDependency,
) -> AssessmentHandoffResponse:
    kwargs = {}
    if payload.provider and payload.provider.lower() != "gmail":
        kwargs["provider"] = payload.provider

    data = await service.handoff_assessment(
        project_id=project_id,
        candidate_ids=payload.candidate_ids,
        requisition_ref=payload.requisition_ref,
        **kwargs,
    )
    return AssessmentHandoffResponse(data=data)


@router.get(
    "/projects/{project_id}/assessment/status",
    status_code=status.HTTP_200_OK,
    summary="Get CD-Recruit evaluation status for project requisition",
    description="Queries current assessment evaluation status for the given project.",
    responses=ERRORS,
)
async def get_assessment_status(
    project_id: UUID,
    service: AssessmentDependency,
) -> dict:
    from app.services.cd_recruit_poller import CDRecruitStatusPoller
    poller = CDRecruitStatusPoller(db=service.projects.db)
    requisition_ref = f"REQ-{project_id}"
    return await poller.poll_requisition(requisition_ref)

