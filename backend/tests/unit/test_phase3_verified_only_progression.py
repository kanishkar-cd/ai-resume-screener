"""Unit tests for Phase 3: Enforce Verified-Only Progression Gate.

Covers:
1. Bulk Scoring (_is_eligible):
   - VERIFIED documents proceed.
   - REVIEW_REQUIRED, REJECTED, FAILED, and missing verification documents are excluded.
   - Raises NoEligibleResumesException when no VERIFIED documents exist.
2. Direct Scoring (score_document):
   - VERIFIED document can be scored directly.
   - REVIEW_REQUIRED document raises CandidateNotVerifiedException (HTTP 400).
   - REJECTED document raises CandidateNotVerifiedException.
   - FAILED document raises CandidateNotVerifiedException.
   - Missing verification status raises CandidateNotVerifiedException.
3. Score Retrieval (get_document_score):
   - VERIFIED document score can be retrieved.
   - Unverified / review-required document raises CandidateNotVerifiedException.
4. Ranking & Shortlisting Gate (compute_project_rankings):
   - Excludes REVIEW_REQUIRED, REJECTED, and unverified documents from ranking/shortlist.
   - Only VERIFIED candidates enter ranking calculation and leaderboard.
   - Raises NoScoredCandidatesException when no verified candidates are available.
5. Assessment Handoff Gate (handoff_assessment):
   - VERIFIED candidate can be handed off to CD-Recruit.
   - REVIEW_REQUIRED candidate raises CandidateNotVerifiedException.
   - REJECTED candidate raises CandidateNotVerifiedException.
   - Missing verification candidate raises CandidateNotVerifiedException.
6. Document-Level Isolation:
   - One approved document does NOT make sibling documents eligible.
   - Approving doc1 does not permit doc2 (sibling under same candidate) to be scored or handed off.
7. FastAPI Route-Level Status & Error Contracts (via AsyncClient).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4
import httpx
import pytest

from app.core.exceptions import CandidateNotVerifiedException
from app.models.document import DocumentModel, DocumentTypeEnum, ProcessingStatusEnum
from app.models.scoring import CandidateScoreModel, RecommendationLevelEnum
from app.schemas.candidate_verification import (
    CandidateVerificationStatus,
    is_document_verified,
)
from app.schemas.matching import MatchMethod, MatchStatus, MatchVerdict
from app.services.assessment_service import AssessmentService
from app.services.ranking_service import NoScoredCandidatesException, RankingService
from app.services.scoring_service import (
    NoEligibleResumesException,
    ScoringEngineFacade,
)


def _create_mock_resume(
    project_id: UUID,
    doc_id: UUID | None = None,
    verification_status: str | None = None,
    processing_status: ProcessingStatusEnum = ProcessingStatusEnum.COMPLETED,
) -> DocumentModel:
    doc = DocumentModel(
        id=doc_id or uuid4(),
        project_id=project_id,
        document_type=DocumentTypeEnum.RESUME,
        processing_status=processing_status,
        original_filename="sample_resume.pdf",
    )
    from datetime import datetime, UTC
    doc.created_at = datetime.now(UTC)
    if verification_status is not None:
        doc.metadata_json = {
            "verification": {
                "verification_status": verification_status,
                "reasons": ["Automated test record"],
            }
        }
    else:
        doc.metadata_json = {}
    return doc


# ==============================================================================
# 1. Bulk Scoring Gate Tests (_is_eligible)
# ==============================================================================


@pytest.mark.asyncio
async def test_bulk_scoring_only_scores_verified_resumes() -> None:
    """Project with mixed statuses: only VERIFIED resumes pass _is_eligible."""
    project_id = uuid4()
    doc_verified = _create_mock_resume(project_id, verification_status="VERIFIED")
    doc_review_req = _create_mock_resume(project_id, verification_status="REVIEW_REQUIRED")
    doc_rejected = _create_mock_resume(project_id, verification_status="REJECTED")
    doc_failed = _create_mock_resume(project_id, verification_status="FAILED")
    doc_missing = _create_mock_resume(project_id, verification_status=None)

    all_resumes = [doc_verified, doc_review_req, doc_rejected, doc_failed, doc_missing]

    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(return_value=MagicMock())

    mock_documents = MagicMock()
    mock_documents.list_resumes_by_project = AsyncMock(return_value=(all_resumes, len(all_resumes)))
    mock_documents.get_job_description_by_project = AsyncMock(return_value=MagicMock(id=uuid4()))

    norm_models = [
        MagicMock(document_id=d.id, experience=[], skills=[], job_titles=[], education=[])
        for d in all_resumes
    ]
    ext_models = [
        MagicMock(document_id=d.id, projects=[], candidate_name=f"Candidate {d.id}")
        for d in all_resumes
    ]

    mock_normalizations = MagicMock()
    mock_normalizations.get_job_description_by_document_id = AsyncMock(
        return_value=MagicMock(skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    )
    mock_normalizations.get_resumes_by_document_ids = AsyncMock(return_value=norm_models)

    mock_extractions = MagicMock()
    mock_extractions.get_resumes_by_document_ids = AsyncMock(return_value=ext_models)

    mock_scores = MagicMock()
    mock_scores.upsert_score = AsyncMock(
        side_effect=lambda data, *args, **kwargs: MagicMock(id=uuid4(), **data.model_dump())
    )

    facade = ScoringEngineFacade(
        projects=mock_projects,
        documents=mock_documents,
        normalizations=mock_normalizations,
        extractions=mock_extractions,
        scores=mock_scores,
    )
    facade.hybrid_matching.match = AsyncMock(side_effect=RuntimeError("hybrid unavailable"))

    result = await facade.score_project(project_id)

    # Exactly 1 evaluated document: the VERIFIED one
    assert result.total_evaluated == 1
    assert result.scores[0].document_id == doc_verified.id


@pytest.mark.asyncio
async def test_bulk_scoring_raises_when_no_resumes_are_verified() -> None:
    """If project has only REVIEW_REQUIRED, REJECTED, or unverified documents, scoring halts."""
    project_id = uuid4()
    resumes = [
        _create_mock_resume(project_id, verification_status="REVIEW_REQUIRED"),
        _create_mock_resume(project_id, verification_status="REJECTED"),
        _create_mock_resume(project_id, verification_status=None),
    ]

    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(return_value=MagicMock())

    mock_documents = MagicMock()
    mock_documents.list_resumes_by_project = AsyncMock(return_value=(resumes, len(resumes)))
    mock_documents.get_job_description_by_project = AsyncMock(return_value=MagicMock(id=uuid4()))

    mock_normalizations = MagicMock()
    mock_normalizations.get_job_description_by_document_id = AsyncMock(
        return_value=MagicMock(skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    )
    mock_normalizations.get_resumes_by_document_ids = AsyncMock(
        return_value=[MagicMock(document_id=d.id) for d in resumes]
    )

    mock_extractions = MagicMock()
    mock_extractions.get_resumes_by_document_ids = AsyncMock(
        return_value=[MagicMock(document_id=d.id) for d in resumes]
    )

    facade = ScoringEngineFacade(
        projects=mock_projects,
        documents=mock_documents,
        normalizations=mock_normalizations,
        extractions=mock_extractions,
        scores=MagicMock(),
    )

    with pytest.raises(NoEligibleResumesException):
        await facade.score_project(project_id)


# ==============================================================================
# 2. Direct Scoring Gate Tests (score_document)
# ==============================================================================


@pytest.mark.asyncio
async def test_direct_scoring_permits_verified_document() -> None:
    project_id = uuid4()
    doc = _create_mock_resume(project_id, verification_status="VERIFIED")

    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(return_value=MagicMock())

    mock_documents = MagicMock()
    mock_documents.get_document = AsyncMock(return_value=doc)
    mock_documents.get_job_description_by_project = AsyncMock(return_value=MagicMock(id=uuid4()))

    mock_normalizations = MagicMock()
    mock_normalizations.get_job_description_by_document_id = AsyncMock(
        return_value=MagicMock(skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    )
    mock_normalizations.get_resume_by_document_id = AsyncMock(
        return_value=MagicMock(experience=[], skills=[], job_titles=[], education=[])
    )

    mock_extractions = MagicMock()
    mock_extractions.get_resume_by_document_id = AsyncMock(
        return_value=MagicMock(projects=[], candidate_name="Verified Candidate")
    )

    mock_scores = MagicMock()
    mock_scores.upsert_score = AsyncMock(
        side_effect=lambda data, *args, **kwargs: MagicMock(id=uuid4(), **data.model_dump())
    )

    facade = ScoringEngineFacade(
        projects=mock_projects,
        documents=mock_documents,
        normalizations=mock_normalizations,
        extractions=mock_extractions,
        scores=mock_scores,
    )
    facade.hybrid_matching.match = AsyncMock(side_effect=RuntimeError("hybrid unavailable"))

    result = await facade.score_document(project_id, doc.id)
    assert result.document_id == doc.id


@pytest.mark.parametrize("status_val", ["REVIEW_REQUIRED", "REJECTED", "FAILED", None])
@pytest.mark.asyncio
async def test_direct_scoring_rejects_unverified_documents(status_val: str | None) -> None:
    project_id = uuid4()
    doc = _create_mock_resume(project_id, verification_status=status_val)

    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(return_value=MagicMock())

    mock_documents = MagicMock()
    mock_documents.get_document = AsyncMock(return_value=doc)
    mock_documents.get_job_description_by_project = AsyncMock(return_value=MagicMock(id=uuid4()))

    facade = ScoringEngineFacade(
        projects=mock_projects,
        documents=mock_documents,
        normalizations=MagicMock(),
        extractions=MagicMock(),
        scores=MagicMock(),
    )

    with pytest.raises(CandidateNotVerifiedException) as exc_info:
        await facade.score_document(project_id, doc.id)

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "CANDIDATE_NOT_VERIFIED"


# ==============================================================================
# 3. Direct Score Query Gate (get_document_score)
# ==============================================================================


@pytest.mark.asyncio
async def test_get_document_score_rejects_unverified_document() -> None:
    doc = _create_mock_resume(uuid4(), verification_status="REVIEW_REQUIRED")
    mock_documents = MagicMock()
    mock_documents.get_document = AsyncMock(return_value=doc)

    facade = ScoringEngineFacade(
        projects=MagicMock(),
        documents=mock_documents,
        normalizations=MagicMock(),
        extractions=MagicMock(),
        scores=MagicMock(),
    )

    with pytest.raises(CandidateNotVerifiedException):
        await facade.get_document_score(doc.id)


# ==============================================================================
# 4. Ranking & Shortlisting Gate Tests (compute_project_rankings)
# ==============================================================================


@pytest.mark.asyncio
async def test_ranking_excludes_unverified_candidates() -> None:
    project_id = uuid4()
    doc_verified = _create_mock_resume(project_id, verification_status="VERIFIED")
    doc_review_req = _create_mock_resume(project_id, verification_status="REVIEW_REQUIRED")
    doc_rejected = _create_mock_resume(project_id, verification_status="REJECTED")

    score_verified = SimpleNamespace(
        id=uuid4(),
        document_id=doc_verified.id,
        final_score=92.0,
        skills_score=90.0,
        experience_score=90.0,
        recommendation=RecommendationLevelEnum.SHORTLIST,
        confidence=0.95,
        is_knocked_out=False,
    )
    score_review_req = SimpleNamespace(
        id=uuid4(),
        document_id=doc_review_req.id,
        final_score=95.0,
        skills_score=90.0,
        experience_score=90.0,
        recommendation=RecommendationLevelEnum.SHORTLIST,
        confidence=0.98,
        is_knocked_out=False,
    )
    score_rejected = SimpleNamespace(
        id=uuid4(),
        document_id=doc_rejected.id,
        final_score=88.0,
        skills_score=85.0,
        experience_score=85.0,
        recommendation=RecommendationLevelEnum.SHORTLIST,
        confidence=0.90,
        is_knocked_out=False,
    )

    scores_list = [score_verified, score_review_req, score_rejected]

    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(return_value=MagicMock(id=project_id))

    mock_scores = MagicMock()
    mock_scores.get_project_scores = AsyncMock(return_value=scores_list)

    mock_documents = MagicMock()
    mock_documents.get_documents_by_ids = AsyncMock(
        return_value=[doc_verified, doc_review_req, doc_rejected]
    )

    upserted_rankings = []
    mock_rankings = MagicMock()
    mock_rankings.get_existing_rankings = AsyncMock(return_value=[])
    mock_rankings.bulk_upsert_rankings = AsyncMock(
        side_effect=lambda proj_id, computed: upserted_rankings.extend(computed)
    )

    service = RankingService(
        projects=mock_projects,
        documents=mock_documents,
        scores=mock_scores,
        rankings=mock_rankings,
    )

    result = await service.compute_project_rankings(project_id)

    # Exactly 1 candidate ranked: only the VERIFIED one
    assert result.total_ranked == 1
    assert len(upserted_rankings) == 1
    assert upserted_rankings[0].document_id == doc_verified.id


@pytest.mark.asyncio
async def test_ranking_raises_when_no_candidates_are_verified() -> None:
    project_id = uuid4()
    doc_review_req = _create_mock_resume(project_id, verification_status="REVIEW_REQUIRED")
    score_review = SimpleNamespace(
        id=uuid4(),
        document_id=doc_review_req.id,
        final_score=85.0,
        recommendation=RecommendationLevelEnum.SHORTLIST,
        confidence=0.9,
        is_knocked_out=False,
    )

    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(return_value=MagicMock(id=project_id))
    mock_scores = MagicMock()
    mock_scores.get_project_scores = AsyncMock(return_value=[score_review])
    mock_documents = MagicMock()
    mock_documents.get_documents_by_ids = AsyncMock(return_value=[doc_review_req])

    service = RankingService(
        projects=mock_projects,
        documents=mock_documents,
        scores=mock_scores,
        rankings=MagicMock(),
    )

    with pytest.raises(NoScoredCandidatesException):
        await service.compute_project_rankings(project_id)


# ==============================================================================
# 5. Assessment Handoff Gate Tests (handoff_assessment)
# ==============================================================================


@pytest.mark.asyncio
async def test_assessment_handoff_permits_verified_candidate() -> None:
    project_id = uuid4()
    doc = _create_mock_resume(project_id, verification_status="VERIFIED")

    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=project_id,
            title="SRE Drive",
            department="SOFTWARE_ENGINEERING",
            metadata_json={},
        )
    )
    mock_documents = MagicMock()
    mock_documents.get_document = AsyncMock(return_value=doc)

    mock_extractions = MagicMock()
    mock_extractions.get_resume_by_document_id = AsyncMock(
        return_value=SimpleNamespace(
            candidate_name="Verified Applicant",
            email="verified@example.com",
            phone="+1234567890",
            experience=[{"duration_months": 36}],
        )
    )

    mock_cd_recruit = MagicMock()
    mock_cd_recruit.send_candidates = AsyncMock(
        return_value={
            "drive_id": "DRIVE_123",
            "data": {
                "invites": [
                    {
                        "external_candidate_ref": str(doc.id),
                        "assessment_link": "https://assess.cd-recruit.com/test-token",
                    }
                ]
            },
        }
    )

    service = AssessmentService(
        projects=mock_projects,
        documents=mock_documents,
        extractions=mock_extractions,
        scores=None,
        cd_recruit=mock_cd_recruit,
        email_service=MagicMock(),
        assessments=None,
    )

    handoff = await service.handoff_assessment(
        project_id=project_id,
        candidate_ids=[doc.id],
        requisition_ref="REQ-100",
    )

    assert handoff.total_invited == 1
    assert handoff.candidates[0].candidate_id == doc.id
    assert handoff.candidates[0].assessment_link == "https://assess.cd-recruit.com/test-token"


@pytest.mark.parametrize("status_val", ["REVIEW_REQUIRED", "REJECTED", "FAILED", None])
@pytest.mark.asyncio
async def test_assessment_handoff_rejects_unverified_candidate(status_val: str | None) -> None:
    project_id = uuid4()
    doc = _create_mock_resume(project_id, verification_status=status_val)

    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=project_id,
            title="SRE Drive",
            department="SOFTWARE_ENGINEERING",
            metadata_json={},
        )
    )
    mock_documents = MagicMock()
    mock_documents.get_document = AsyncMock(return_value=doc)

    service = AssessmentService(
        projects=mock_projects,
        documents=mock_documents,
        extractions=MagicMock(),
        scores=None,
        cd_recruit=MagicMock(),
        email_service=MagicMock(),
        assessments=None,
    )

    with pytest.raises(CandidateNotVerifiedException) as exc_info:
        await service.handoff_assessment(
            project_id=project_id,
            candidate_ids=[doc.id],
            requisition_ref="REQ-100",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "CANDIDATE_NOT_VERIFIED"


# ==============================================================================
# 6. Document-Level Isolation (Sibling Documents Under Same Candidate)
# ==============================================================================


@pytest.mark.asyncio
async def test_document_level_isolation_sibling_document_remains_ineligible() -> None:
    """Approving doc1 must NOT make sibling doc2 for the same candidate eligible."""
    project_id = uuid4()
    doc1_approved = _create_mock_resume(project_id, verification_status="VERIFIED")
    doc2_sibling = _create_mock_resume(project_id, verification_status="REVIEW_REQUIRED")

    # Verify helper semantics directly
    assert is_document_verified(doc1_approved) is True
    assert is_document_verified(doc2_sibling) is False

    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(return_value=MagicMock())

    def _get_doc(doc_id):
        if doc_id == doc1_approved.id:
            return doc1_approved
        if doc_id == doc2_sibling.id:
            return doc2_sibling
        return None

    mock_documents = MagicMock()
    mock_documents.get_document = AsyncMock(side_effect=_get_doc)
    mock_documents.get_job_description_by_project = AsyncMock(return_value=MagicMock(id=uuid4()))

    mock_normalizations = MagicMock()
    mock_normalizations.get_job_description_by_document_id = AsyncMock(
        return_value=MagicMock(skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    )
    mock_normalizations.get_resume_by_document_id = AsyncMock(
        return_value=MagicMock(experience=[], skills=[], job_titles=[], education=[])
    )

    mock_extractions = MagicMock()
    mock_extractions.get_resume_by_document_id = AsyncMock(
        return_value=SimpleNamespace(
            candidate_name="Candidate",
            email="candidate@example.com",
            phone="+1234567890",
            experience=[{"duration_months": 12}],
            projects=[],
        )
    )

    mock_scores = MagicMock()
    mock_scores.upsert_score = AsyncMock(
        side_effect=lambda data, *args, **kwargs: MagicMock(id=uuid4(), **data.model_dump())
    )

    facade = ScoringEngineFacade(
        projects=mock_projects,
        documents=mock_documents,
        normalizations=mock_normalizations,
        extractions=mock_extractions,
        scores=mock_scores,
    )
    facade.hybrid_matching.match = AsyncMock(side_effect=RuntimeError("hybrid unavailable"))

    # doc1 can be scored
    res1 = await facade.score_document(project_id, doc1_approved.id)
    assert res1.document_id == doc1_approved.id

    # doc2 CANNOT be scored
    with pytest.raises(CandidateNotVerifiedException):
        await facade.score_document(project_id, doc2_sibling.id)

    # In assessment handoff: doc1 succeeds, doc2 fails
    mock_projects.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=project_id,
            title="SRE Drive",
            department="SOFTWARE_ENGINEERING",
            metadata_json={},
        )
    )
    mock_cd_recruit = MagicMock()
    mock_cd_recruit.settings = SimpleNamespace(
        CD_RECRUIT_DEFAULT_DEPARTMENT_CODE="SOFTWARE_ENGINEERING",
        CD_RECRUIT_BASE_URL="http://127.0.0.1:3001",
        ENABLE_ASSESSMENT_EMAILS=False,
    )
    mock_cd_recruit.send_candidates = AsyncMock(
        return_value={"drive_id": "DRIVE_1", "data": {"invites": [{"external_candidate_ref": str(doc1_approved.id)}]}}
    )

    assessment_service = AssessmentService(
        projects=mock_projects,
        documents=mock_documents,
        extractions=mock_extractions,
        cd_recruit=mock_cd_recruit,
        email_service=MagicMock(),
    )

    # doc1 handoff succeeds
    handoff_res = await assessment_service.handoff_assessment(
        project_id=project_id, candidate_ids=[doc1_approved.id], requisition_ref="REQ-1"
    )
    assert handoff_res.total_invited == 1

    # doc2 handoff fails
    with pytest.raises(CandidateNotVerifiedException):
        await assessment_service.handoff_assessment(
            project_id=project_id, candidate_ids=[doc2_sibling.id], requisition_ref="REQ-1"
        )


# ==============================================================================
# 7. FastAPI Route Status Code & Error Contract Tests (AsyncClient)
# ==============================================================================


@pytest.mark.asyncio
async def test_api_direct_scoring_unverified_returns_400(async_client: httpx.AsyncClient) -> None:
    from app.main import app
    from app.api.v1.endpoints.scoring import get_scoring_facade

    project_id = uuid4()
    doc_id = uuid4()

    mock_facade = MagicMock()
    mock_facade.score_document = AsyncMock(
        side_effect=CandidateNotVerifiedException("Document not verified.")
    )

    app.dependency_overrides[get_scoring_facade] = lambda: mock_facade

    try:
        res = await async_client.post(f"/api/v1/projects/{project_id}/documents/{doc_id}/score")
        assert res.status_code == 400
        data = res.json()
        assert data["error"]["code"] == "CANDIDATE_NOT_VERIFIED"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_assessment_handoff_unverified_returns_400(async_client: httpx.AsyncClient) -> None:
    from app.main import app
    from app.api.v1.endpoints.assessment import get_assessment_service

    project_id = uuid4()
    cand_id = uuid4()

    mock_service = MagicMock()
    mock_service.handoff_assessment = AsyncMock(
        side_effect=CandidateNotVerifiedException("Candidate document not verified.")
    )

    app.dependency_overrides[get_assessment_service] = lambda: mock_service

    try:
        res = await async_client.post(
            f"/api/v1/projects/{project_id}/assessment/handoff",
            json={"candidate_ids": [str(cand_id)], "requisition_ref": "REQ-100"},
        )
        assert res.status_code == 400
        data = res.json()
        assert data["error"]["code"] == "CANDIDATE_NOT_VERIFIED"
    finally:
        app.dependency_overrides.clear()
