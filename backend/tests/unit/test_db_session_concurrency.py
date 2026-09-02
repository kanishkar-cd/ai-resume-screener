import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
import pytest

from app.models.document import DocumentModel, DocumentTypeEnum
from app.schemas.matching import Requirement, RequirementKind, Evidence, MatchStatus, MatchVerdict, MatchMethod
from app.services.scoring_service import ScoringEngineFacade


@pytest.mark.asyncio
async def test_3_concurrent_resumes_independent_db_sessions():
    """
    Verify 3 concurrent resume scoring operations create 3 distinct AsyncSessions
    without interface errors or IllegalStateChangeError.
    """
    session_identities = set()
    session_lock = asyncio.Lock()

    # Create 3 mock documents
    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)
    doc2 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)
    doc3 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    resumes = [doc1, doc2, doc3]
    doc_ids = [d.id for d in resumes]

    # Mock repositories & dependencies
    project_repo = AsyncMock()
    doc_repo = AsyncMock()
    doc_repo.list_resumes_by_project.return_value = (resumes, 3)

    norm_repo = AsyncMock()
    norm_model = SimpleNamespace(
        id=uuid4(),
        document_id=doc1.id,
        raw_text="Python Engineer",
        skills=["Python"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=d.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
        for d in resumes
    ]

    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=d.id, skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
        for d in resumes
    ]

    from datetime import datetime, timezone
    from app.repositories.scoring_repository import ScoringRepository

    from app.models.scoring import RecommendationLevelEnum

    scores_repo = ScoringRepository(MagicMock())
    def _make_score_model(score_create, **kwargs):
        now = datetime.now(timezone.utc)
        doc_id = score_create.document_id if hasattr(score_create, 'document_id') else UUID(score_create['document_id'])
        proj_id = score_create.project_id if hasattr(score_create, 'project_id') else UUID(score_create['project_id'])
        comp_detail = {"score": 100.0, "matched_items": [], "missing_items": [], "explanation": "Good"}
        return SimpleNamespace(
            id=uuid4(),
            document_id=doc_id,
            project_id=proj_id,
            skills_score=100.0,
            experience_score=100.0,
            projects_score=100.0,
            education_score=100.0,
            certifications_score=100.0,
            languages_score=100.0,
            component_scores={
                "skills": comp_detail,
                "experience": comp_detail,
                "projects": comp_detail,
                "education": comp_detail,
                "certifications": comp_detail,
                "languages": comp_detail,
            },
            weighted_scores={
                "skills": 30.0,
                "experience": 30.0,
                "projects": 20.0,
                "education": 10.0,
                "certifications": 10.0,
            },
            raw_total_score=100.0,
            weighted_total_score=100.0,
            penalty_total=0.0,
            bonus_total=0.0,
            final_score=100.0,
            confidence=1.0,
            recommendation=RecommendationLevelEnum.SHORTLIST,
            is_knocked_out=False,
            knockout_reason=None,
            penalty_summary=[],
            bonus_summary=[],
            passing_score=70.0,
            effective_weights={},
            score_breakdown=[],
            weight_config_version=1,
            matched_skills=[],
            missing_skills=[],
            strengths=[],
            weaknesses=[],
            match_verdicts=[],
            created_at=now,
            updated_at=now,
        )
    scores_repo.upsert_score = AsyncMock(side_effect=_make_score_model)

    weights_repo = AsyncMock()
    weights_repo.get_by_project_id.return_value = SimpleNamespace(passing_score=70.0)

    job_mock = SimpleNamespace(
        id=uuid4(),
        title="Software Engineer",
        required_skills=["Python"],
        skills=["Python"],
        responsibilities=[],
        experience_months=0,
        education_level=None,
    )

    facade = ScoringEngineFacade(
        projects=project_repo,
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=scores_repo,
        weights=weights_repo,
    )

    facade._load_project_context = AsyncMock(return_value=job_mock)
    facade.hybrid_matching = MagicMock()
    facade.hybrid_matching.match = AsyncMock(return_value=(
        SimpleNamespace(projects=[]),
        [MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, method=MatchMethod.EXACT)]
    ))

    # Mock AsyncSessionLocal to record session identities
    class MockSessionContext:
        def __init__(self):
            self.mock_session = AsyncMock()
            self.mock_session.add = MagicMock()
            self.mock_session.scalar = AsyncMock(return_value=None)
            self.mock_session.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            self.mock_session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
            self.mock_session.commit = AsyncMock()
            self.mock_session.rollback = AsyncMock()

        async def __aenter__(self):
            async with session_lock:
                session_identities.add(hex(id(self.mock_session)))
            return self.mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.services.scoring_service.AsyncSessionLocal", side_effect=MockSessionContext), \
         patch.object(ScoringRepository, "upsert_score", side_effect=_make_score_model):
        result = await facade.score_project(project_id)

    assert result.total_evaluated == 3
    assert len(result.scores) == 3
    assert len(session_identities) >= 3
