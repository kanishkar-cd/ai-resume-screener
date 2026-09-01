from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, status

from app.api.deps import DatabaseDependency
from app.repositories.assessment_repository import AssessmentRepository
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
        assessments=AssessmentRepository(db),
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
    db: DatabaseDependency,
) -> dict:
    from app.services.cd_recruit_poller import CDRecruitStatusPoller
    from app.repositories.project_repository import ProjectRepository
    from app.repositories.document_repository import DocumentRepository
    from app.repositories.extraction_repository import ExtractionRepository
    from app.models.assessment_invitation import CandidateAssessmentModel
    from sqlalchemy import select

    stmt = select(CandidateAssessmentModel.requisition_ref).where(
        CandidateAssessmentModel.project_id == project_id
    ).limit(1)
    res = await db.execute(stmt)
    requisition_ref = res.scalar()

    if not requisition_ref:
        proj_repo = ProjectRepository(db)
        project = await proj_repo.get_by_id(project_id)
        if project:
            meta = getattr(project, "metadata_json", {}) or {}
            if isinstance(meta, dict):
                requisition_ref = meta.get("req_ref")

    if not requisition_ref:
        requisition_ref = f"REQ-{project_id}"

    poller = CDRecruitStatusPoller(db=db)
    poll_result = await poller.poll_requisition(requisition_ref)

    stmt = select(CandidateAssessmentModel).where(
        CandidateAssessmentModel.project_id == project_id
    )
    records = list((await db.execute(stmt)).scalars().all())

    candidates_list = []
    extraction_repo = ExtractionRepository(db)
    doc_repo = DocumentRepository(db)

    for rec in records:
        cand_name = None
        cand_email = None
        try:
            ext = await extraction_repo.get_resume_by_document_id(rec.document_id)
            if ext:
                cand_name = getattr(ext, "candidate_name", None)
                cand_email = getattr(ext, "email", None)
        except Exception:
            pass

        if not cand_name:
            try:
                doc = await doc_repo.get_document(rec.document_id)
                cand_name = getattr(doc, "original_filename", None) or "Candidate"
            except Exception:
                cand_name = "Candidate"

        if not cand_email:
            cand_email = f"candidate_{str(rec.document_id)[:8]}@example.com"

        candidates_list.append({
            "candidate_id": str(rec.document_id),
            "external_candidate_ref": str(rec.external_candidate_ref or rec.document_id),
            "candidate_name": cand_name,
            "email": cand_email,
            "assessment_link": rec.assessment_link,
            "session_status": rec.session_status,
            "score_status": rec.score_status,
            "composite_score": rec.composite_score,
            "composite_score_band": rec.composite_score_band,
            "identity_status": rec.identity_status,
            "is_identity_verified": rec.is_identity_verified,
            "started_at": rec.started_at.isoformat() if rec.started_at else None,
            "submitted_at": rec.submitted_at.isoformat() if rec.submitted_at else None,
            "expires_at": rec.expires_at.isoformat() if rec.expires_at else None,
            "decision": rec.decision,
        })

    # Auto-transition project to COMPLETED if all candidate assessments have recorded results
    if records:
        all_completed = all(
            (rec.score_status in ("graded", "scored") or rec.composite_score is not None or rec.decision is not None)
            and rec.session_status in ("submitted", "completed")
            for rec in records
        )
        if all_completed:
            from app.models.project import ProjectModel, ProjectStatusEnum
            p_stmt = select(ProjectModel).where(ProjectModel.id == project_id)
            p_obj = await db.scalar(p_stmt)
            if p_obj and p_obj.status != ProjectStatusEnum.COMPLETED:
                p_obj.status = ProjectStatusEnum.COMPLETED
                await db.commit()

    return {
        "requisition_ref": requisition_ref,
        "session_status": poll_result.get("session_status", "not_started"),
        "score_status": poll_result.get("score_status", "not_graded"),
        "composite_score_band": poll_result.get("composite_score_band"),
        "decision": poll_result.get("decision"),
        "candidates": candidates_list,
    }

