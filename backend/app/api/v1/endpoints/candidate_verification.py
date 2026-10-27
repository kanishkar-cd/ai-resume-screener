from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import DatabaseDependency, get_current_user_dep
from app.schemas.candidate_verification import (
    BatchVerificationRequest,
    BatchVerificationResponse,
    BatchVerificationSummary,
    CandidateManualReviewRequest,
    CandidateManualReviewResponse,
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
DocumentId = Annotated[UUID, Path(description="Resume Document UUID")]
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
    "/projects/{project_id}/documents/{document_id}/review",
    response_model=CandidateManualReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit manual candidate identity review decision",
    description=(
        "Manually approve or reject a candidate resume whose identity requires review. "
        "Validates project and document ownership and ensures current status is REVIEW_REQUIRED."
    ),
    responses={
        **ERRORS,
        422: {"model": ErrorResponsePayload, "description": "Validation error or invalid review decision."},
    },
)
async def review_candidate_document(
    project_id: ProjectId,
    document_id: DocumentId,
    payload: CandidateManualReviewRequest,
    service: VerificationServiceDependency,
    current_user: Any = Depends(get_current_user_dep),
) -> CandidateManualReviewResponse:
    reviewer_id = None
    if current_user:
        reviewer_id = (
            getattr(current_user, "id", None)
            or getattr(current_user, "email", None)
            or str(current_user)
        )
    result = await service.review_candidate_document(
        project_id=project_id,
        document_id=document_id,
        payload=payload,
        reviewer_id=reviewer_id,
    )
    return CandidateManualReviewResponse(data=result)


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
