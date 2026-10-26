from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import DatabaseDependency
from app.schemas.candidate_verification import (
    BatchVerificationRequest,
    BatchVerificationResponse,
    BatchVerificationSummary,
)
from app.schemas.error import ErrorResponsePayload
from app.services.candidate_verification_service import CandidateVerificationService

router = APIRouter()

ERRORS = {
    400: {"model": ErrorResponsePayload, "description": "Invalid verification request."},
    404: {"model": ErrorResponsePayload, "description": "Job opening or project not found."},
    500: {"model": ErrorResponsePayload, "description": "Internal verification error."},
}


def get_candidate_verification_service(db: DatabaseDependency) -> CandidateVerificationService:
    return CandidateVerificationService(session=db)


VerificationServiceDependency = Annotated[
    CandidateVerificationService, Depends(get_candidate_verification_service)
]
ProjectId = Annotated[UUID, Path(description="Project UUID")]
JobId = Annotated[str, Path(description="Zoho Job Opening ID or Project ID")]


@router.post(
    "/projects/{project_id}/verify-candidates",
    response_model=BatchVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify all candidates in a project",
    description=(
        "Trigger deterministic batch candidate verification for all candidates associated "
        "with this project / job opening (Phase 1 normalization, Phase 2 identity matching, "
        "and Phase 3 repeat-application detection)."
    ),
    responses=ERRORS,
)
async def verify_project_candidates(
    project_id: ProjectId,
    service: VerificationServiceDependency,
    payload: BatchVerificationRequest | None = None,
) -> BatchVerificationResponse:
    force = payload.force_reverify if payload else False
    summary = await service.verify_job_opening_candidates(project_id, force_reverify=force)
    return BatchVerificationResponse(data=summary)


@router.get(
    "/projects/{project_id}/verification-status",
    response_model=BatchVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get candidate verification status",
    description="Retrieve the latest candidate verification status, aggregate counts, and candidate results.",
    responses=ERRORS,
)
async def get_project_verification_status(
    project_id: ProjectId,
    service: VerificationServiceDependency,
) -> BatchVerificationResponse:
    summary = await service.get_verification_status(project_id)
    return BatchVerificationResponse(data=summary)


@router.post(
    "/projects/{project_id}/verify-candidates/retry",
    response_model=BatchVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Retry failed candidate verifications",
    description="Safely retry only unverified, failed, or review-required candidates in the project.",
    responses=ERRORS,
)
async def retry_project_candidate_verification(
    project_id: ProjectId,
    service: VerificationServiceDependency,
) -> BatchVerificationResponse:
    summary = await service.retry_failed_candidates(project_id)
    return BatchVerificationResponse(data=summary)


@router.post(
    "/zoho/job-openings/{job_id}/verify-candidates",
    response_model=BatchVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify all candidates for a Zoho Job Opening",
    description="Trigger batch candidate verification using a Zoho Job Opening identifier.",
    responses=ERRORS,
)
async def verify_zoho_job_candidates(
    job_id: JobId,
    service: VerificationServiceDependency,
    payload: BatchVerificationRequest | None = None,
) -> BatchVerificationResponse:
    force = payload.force_reverify if payload else False
    summary = await service.verify_job_opening_candidates(job_id, force_reverify=force)
    return BatchVerificationResponse(data=summary)


@router.get(
    "/zoho/job-openings/{job_id}/verification-status",
    response_model=BatchVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Zoho Job Opening candidate verification status",
    responses=ERRORS,
)
async def get_zoho_job_verification_status(
    job_id: JobId,
    service: VerificationServiceDependency,
) -> BatchVerificationResponse:
    summary = await service.get_verification_status(job_id)
    return BatchVerificationResponse(data=summary)
