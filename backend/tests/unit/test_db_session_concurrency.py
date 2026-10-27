import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4
import pytest

from app.models.document import DocumentModel, DocumentTypeEnum
from app.models.scoring import RecommendationLevelEnum
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.matching import Requirement, RequirementKind, Evidence, MatchStatus, MatchVerdict, MatchMethod
from app.schemas.scoring import CandidateScoreRead
from app.services.scoring_service import ScoringEngineFacade


@pytest.fixture(autouse=True)
def default_verified_documents(monkeypatch):
    orig_init = DocumentModel.__init__
    def patched_init(self, *args, **kwargs):
        if "metadata_json" not in kwargs:
            kwargs["metadata_json"] = {"verification": {"verification_status": "VERIFIED"}}
        orig_init(self, *args, **kwargs)
    monkeypatch.setattr(DocumentModel, "__init__", patched_init)


def _make_score_model(score_create, **kwargs):
    now = datetime.now(timezone.utc)
    doc_id = score_create.document_id if hasattr(score_create, 'document_id') else UUID(str(score_create['document_id']))
    proj_id = score_create.project_id if hasattr(score_create, 'project_id') else UUID(str(score_create['project_id']))
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


@pytest.mark.asyncio
async def test_outer_read_transaction_ends_before_scoring():
    """Verify that the outer session's read transaction is explicitly committed before concurrent scoring."""
    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    mock_outer_session = AsyncMock()
    mock_outer_session.in_transaction = MagicMock(return_value=True)
    mock_outer_session.dirty = set()
    mock_outer_session.new = set()
    mock_outer_session.deleted = set()
    mock_outer_session.commit = AsyncMock()

    doc_repo = AsyncMock()
    doc_repo.session = mock_outer_session
    doc_repo.list_resumes_by_project.return_value = ([doc1], 1)

    norm_repo = AsyncMock()
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ]

    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ]

    weights_repo = AsyncMock()
    weights_repo.get_by_project_id.return_value = SimpleNamespace(passing_score=70.0)

    job_mock = SimpleNamespace(
        id=uuid4(), title="Software Engineer", required_skills=["Python"], skills=["Python"],
        responsibilities=[], experience_months=0, education_level=None,
    )

    scores_repo = AsyncMock()

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=scores_repo,
        weights=weights_repo,
    )
    facade._load_project_context = AsyncMock(return_value=job_mock)
    facade._score = AsyncMock(return_value=CandidateScoreRead.model_validate(_make_score_model(SimpleNamespace(document_id=doc1.id, project_id=project_id))))

    await facade.score_project(project_id)

    # Outer session commit MUST be called to end the read transaction
    mock_outer_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_outer_session_pending_writes_not_silently_committed():
    """Verify that if the outer session has pending/dirty writes, it is not committed."""
    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    mock_outer_session = AsyncMock()
    mock_outer_session.in_transaction = MagicMock(return_value=True)
    mock_outer_session.dirty = [doc1]  # pending write!
    mock_outer_session.new = set()
    mock_outer_session.deleted = set()
    mock_outer_session.commit = AsyncMock()

    doc_repo = AsyncMock()
    doc_repo.session = mock_outer_session
    doc_repo.list_resumes_by_project.return_value = ([doc1], 1)

    norm_repo = AsyncMock()
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ]

    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ]

    weights_repo = AsyncMock()
    weights_repo.get_by_project_id.return_value = SimpleNamespace(passing_score=70.0)

    job_mock = SimpleNamespace(
        id=uuid4(), title="Software Engineer", required_skills=["Python"], skills=["Python"],
        responsibilities=[], experience_months=0, education_level=None,
    )

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=AsyncMock(),
        weights=weights_repo,
    )
    facade._load_project_context = AsyncMock(return_value=job_mock)
    facade._score = AsyncMock(return_value=CandidateScoreRead.model_validate(_make_score_model(SimpleNamespace(document_id=doc1.id, project_id=project_id))))

    await facade.score_project(project_id)

    # Must NOT commit when there are pending writes
    mock_outer_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_weights_no_redundant_per_resume_lookup():
    """Verify that when a project uses default weights (None in DB), get_by_project_id is not called per resume."""
    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)
    doc2 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    doc_repo = AsyncMock()
    doc_repo.list_resumes_by_project.return_value = ([doc1, doc2], 2)

    norm_repo = AsyncMock()
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=d.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
        for d in [doc1, doc2]
    ]

    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=d.id, skills=["Python"], projects=[], candidate_name="Cand")
        for d in [doc1, doc2]
    ]

    weights_repo = AsyncMock()
    weights_repo.get_by_project_id.return_value = None  # Default weights (no custom DB row)

    scores_repo = AsyncMock()
    scores_repo.upsert_score = AsyncMock(side_effect=_make_score_model)

    job_mock = SimpleNamespace(
        id=uuid4(), title="Software Engineer", required_skills=["Python"], skills=["Python"],
        responsibilities=[], experience_months=0, education_level=None,
    )

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=scores_repo,
        weights=weights_repo,
    )
    facade._load_project_context = AsyncMock(return_value=job_mock)
    facade.hybrid_matching = MagicMock()
    facade.hybrid_matching.match = AsyncMock(return_value=(SimpleNamespace(projects=[]), []))

    await facade.score_project(project_id)

    # weights_repo.get_by_project_id should be called exactly ONCE during preloading, NEVER per resume
    assert weights_repo.get_by_project_id.call_count == 1


@pytest.mark.asyncio
async def test_unsupplied_weight_config_fallback_retained():
    """Verify that when _score is called directly without weight_config_checked, it still falls back to query weights."""
    project_id = uuid4()
    doc = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)
    job = SimpleNamespace(
        id=uuid4(), title="Engineer", required_skills=["Python"], skills=["Python"],
        responsibilities=[], experience_months=0, education_level=None,
    )
    resume = SimpleNamespace(skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["Python"], projects=[], candidate_name="Cand")

    weights_repo = AsyncMock()
    weights_repo.get_by_project_id.return_value = SimpleNamespace(passing_score=60.0)

    scores_repo = AsyncMock()
    scores_repo.upsert_score = AsyncMock(side_effect=_make_score_model)

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=AsyncMock(),
        normalizations=AsyncMock(),
        extractions=AsyncMock(),
        scores=scores_repo,
        weights=weights_repo,
    )
    facade.hybrid_matching = MagicMock()
    facade.hybrid_matching.match = AsyncMock(return_value=(SimpleNamespace(projects=[]), []))

    # Calling _score directly with default weight_config_checked=False
    await facade._score(
        doc, job,
        resume=resume,
        extracted=extracted,
        weight_config=None,
        scores_repo=scores_repo,
        weights_repo=weights_repo,
        weight_config_checked=False,
    )

    # weights_repo.get_by_project_id MUST be called when weight_config_checked is False
    weights_repo.get_by_project_id.assert_awaited_once_with(project_id)


@pytest.mark.asyncio
async def test_cleanup_rollback_failure_does_not_mask_original_scoring_exception():
    """Verify that if rollback fails on a closed connection during _scored_task cleanup, the original exception is preserved."""
    from app.core.exceptions import AppException

    class CustomScoringError(AppException):
        default_message = "Original scoring failed"

    project_id = uuid4()
    doc = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    doc_repo = AsyncMock()
    doc_repo.list_resumes_by_project.return_value = ([doc], 1)

    norm_repo = AsyncMock()
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ]
    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc.id, skills=["Python"], projects=[], candidate_name="Cand")
    ]

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=ScoringRepository(MagicMock()),  # real repo to trigger real session branch
        weights=AsyncMock(),
    )
    facade._load_project_context = AsyncMock(return_value=SimpleNamespace(
        id=uuid4(), title="Eng", required_skills=[], skills=[], responsibilities=[], experience_months=0, education_level=None
    ))
    facade._score = AsyncMock(side_effect=CustomScoringError("Original scoring failure"))

    # Mock per-task session whose rollback raises ConnectionDoesNotExistError
    mock_task_session = AsyncMock()
    mock_task_session.rollback.side_effect = RuntimeError("ConnectionDoesNotExistError: connection closed")

    class FailingSessionContext:
        async def __aenter__(self):
            return mock_task_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.services.scoring_service.AsyncSessionLocal", side_effect=FailingSessionContext):
        with pytest.raises(CustomScoringError) as exc_info:
            await facade.score_project(project_id)

    # The original CustomScoringError must be preserved, NOT masked by RuntimeError
    assert "Original scoring failure" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_db_cleanup_failure_does_not_mask_route_exception():
    """Verify that if session.rollback fails during get_db() exception handling, the original route error is raised."""
    from app.db.session import get_db

    mock_db_session = AsyncMock()
    mock_db_session.rollback.side_effect = RuntimeError("cannot call rollback: connection is closed")
    mock_db_session.close.side_effect = RuntimeError("cannot call close: connection is closed")

    class MockContext:
        async def __aenter__(self):
            return mock_db_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.db.session.AsyncSessionLocal", side_effect=MockContext):
        db_gen = get_db()
        session = await anext(db_gen)
        assert session is mock_db_session

        # Route raises ValueError
        with pytest.raises(ValueError) as exc_info:
            await db_gen.athrow(ValueError("Route business logic failure"))

        # Original ValueError must be propagated, not masked by the rollback/close error
        assert "Route business logic failure" in str(exc_info.value)


@pytest.mark.asyncio
async def test_outer_commit_failure_handled_via_safe_rollback():
    """Verify that when outer session commit fails, safe rollback is executed and scoring proceeds if cleanup is confirmed."""
    from sqlalchemy.exc import SQLAlchemyError

    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    mock_outer_session = AsyncMock()
    # in_transaction returns True during preload check, False after rollback
    mock_outer_session.in_transaction = MagicMock(side_effect=[True, False])
    mock_outer_session.dirty = set()
    mock_outer_session.new = set()
    mock_outer_session.deleted = set()
    mock_outer_session.commit = AsyncMock(side_effect=SQLAlchemyError("Outer commit failed"))
    mock_outer_session.rollback = AsyncMock()

    doc_repo = AsyncMock()
    doc_repo.session = mock_outer_session
    doc_repo.list_resumes_by_project.return_value = ([doc1], 1)

    norm_repo = AsyncMock()
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ]
    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, skills=["Python"], projects=[], candidate_name="Cand")
    ]
    weights_repo = AsyncMock()
    weights_repo.get_by_project_id.return_value = SimpleNamespace(passing_score=70.0)

    job_mock = SimpleNamespace(
        id=uuid4(), title="Software Engineer", required_skills=["Python"], skills=["Python"],
        responsibilities=[], experience_months=0, education_level=None,
    )

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=AsyncMock(),
        weights=weights_repo,
    )
    facade._load_project_context = AsyncMock(return_value=job_mock)
    facade._score = AsyncMock(return_value=CandidateScoreRead.model_validate(_make_score_model(SimpleNamespace(document_id=doc1.id, project_id=project_id))))

    result = await facade.score_project(project_id)

    assert result.total_evaluated == 1
    mock_outer_session.commit.assert_awaited_once()
    mock_outer_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_outer_commit_failure_with_failed_cleanup_aborts_scoring():
    """Verify that when outer session commit fails and rollback also fails, scoring aborts with InternalServerException preserving cause."""
    from sqlalchemy.exc import SQLAlchemyError
    from app.core.exceptions import InternalServerException

    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    mock_outer_session = AsyncMock()
    mock_outer_session.in_transaction = MagicMock(return_value=True)
    mock_outer_session.dirty = set()
    mock_outer_session.new = set()
    mock_outer_session.deleted = set()
    commit_err = SQLAlchemyError("Outer commit fatal error")
    mock_outer_session.commit = AsyncMock(side_effect=commit_err)
    mock_outer_session.rollback = AsyncMock(side_effect=SQLAlchemyError("Outer rollback fatal error"))

    doc_repo = AsyncMock()
    doc_repo.session = mock_outer_session
    doc_repo.list_resumes_by_project.return_value = ([doc1], 1)

    norm_repo = AsyncMock()
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ]
    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, skills=["Python"], projects=[], candidate_name="Cand")
    ]
    weights_repo = AsyncMock()
    weights_repo.get_by_project_id.return_value = SimpleNamespace(passing_score=70.0)

    job_mock = SimpleNamespace(
        id=uuid4(), title="Software Engineer", required_skills=["Python"], skills=["Python"],
        responsibilities=[], experience_months=0, education_level=None,
    )

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=AsyncMock(),
        weights=weights_repo,
    )
    facade._load_project_context = AsyncMock(return_value=job_mock)
    facade._score = AsyncMock()

    with pytest.raises(InternalServerException) as exc_info:
        await facade.score_project(project_id)

    assert "Unable to confirm database transaction cleanup before scoring." in str(exc_info.value)
    assert exc_info.value.__cause__ is commit_err
    mock_outer_session.commit.assert_awaited_once()
    mock_outer_session.rollback.assert_awaited_once()
    facade._score.assert_not_called()


@pytest.mark.asyncio
async def test_weight_config_lookup_exception_aborts_without_silent_default_substitution():
    """Verify that a weight configuration query exception aborts scoring instead of silently substituting default weights."""
    from sqlalchemy.exc import SQLAlchemyError
    from app.core.exceptions import InternalServerException

    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    doc_repo = AsyncMock()
    doc_repo.list_resumes_by_project.return_value = ([doc1], 1)

    norm_repo = AsyncMock()
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ]
    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, skills=["Python"], projects=[], candidate_name="Cand")
    ]
    weights_repo = AsyncMock()
    weights_repo.get_by_project_id.side_effect = SQLAlchemyError("Weights DB query error")

    job_mock = SimpleNamespace(
        id=uuid4(), title="Software Engineer", required_skills=["Python"], skills=["Python"],
        responsibilities=[], experience_months=0, education_level=None,
    )

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=AsyncMock(),
        weights=weights_repo,
    )
    facade._load_project_context = AsyncMock(return_value=job_mock)

    with pytest.raises(InternalServerException) as exc_info:
        await facade.score_project(project_id)

    assert "Unable to retrieve project weight configuration." in str(exc_info.value)


@pytest.mark.asyncio
async def test_weight_config_successful_lookup_returning_none_uses_defaults():
    """Verify that a successful lookup returning None is distinguished and legitimate default weights are applied without errors."""
    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    doc_repo = AsyncMock()
    doc_repo.list_resumes_by_project.return_value = ([doc1], 1)

    norm_repo = AsyncMock()
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ]
    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=doc1.id, skills=["Python"], projects=[], candidate_name="Cand")
    ]
    weights_repo = AsyncMock()
    weights_repo.get_by_project_id.return_value = None  # Successful query confirming no custom weights

    job_mock = SimpleNamespace(
        id=uuid4(), title="Software Engineer", required_skills=["Python"], skills=["Python"],
        responsibilities=[], experience_months=0, education_level=None,
    )

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=AsyncMock(),
        weights=weights_repo,
    )
    facade._load_project_context = AsyncMock(return_value=job_mock)
    facade._score = AsyncMock(return_value=CandidateScoreRead.model_validate(_make_score_model(SimpleNamespace(document_id=doc1.id, project_id=project_id))))

    result = await facade.score_project(project_id)

    assert result.total_evaluated == 1
    # Successfully checked and used None
    facade._score.assert_awaited_once()
    _, kwargs = facade._score.call_args
    assert kwargs.get("weight_config") is None
    assert kwargs.get("weight_config_checked") is True


@pytest.mark.asyncio
async def test_no_redundant_weight_queries_when_preload_succeeds():
    """Verify that when preload weight lookup succeeds for 3 resumes, get_by_project_id is called exactly once."""
    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)
    doc2 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)
    doc3 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    doc_repo = AsyncMock()
    doc_repo.list_resumes_by_project.return_value = ([doc1, doc2, doc3], 3)

    norm_repo = AsyncMock()
    norm_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=d.id, raw_text="Python", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
        for d in [doc1, doc2, doc3]
    ]
    ext_repo = AsyncMock()
    ext_repo.get_resumes_by_document_ids.return_value = [
        SimpleNamespace(document_id=d.id, skills=["Python"], projects=[], candidate_name="Cand")
        for d in [doc1, doc2, doc3]
    ]
    weights_repo = AsyncMock()
    custom_cfg = SimpleNamespace(passing_score=80.0)
    weights_repo.get_by_project_id.return_value = custom_cfg

    job_mock = SimpleNamespace(
        id=uuid4(), title="Software Engineer", required_skills=["Python"], skills=["Python"],
        responsibilities=[], experience_months=0, education_level=None,
    )

    facade = ScoringEngineFacade(
        projects=AsyncMock(),
        documents=doc_repo,
        normalizations=norm_repo,
        extractions=ext_repo,
        scores=AsyncMock(),
        weights=weights_repo,
    )
    facade._load_project_context = AsyncMock(return_value=job_mock)
    facade._score = AsyncMock(side_effect=lambda doc, *args, **kwargs: CandidateScoreRead.model_validate(
        _make_score_model(SimpleNamespace(document_id=doc.id, project_id=project_id))
    ))

    result = await facade.score_project(project_id)

    assert result.total_evaluated == 3
    # Exactly one query across all 3 resumes
    assert weights_repo.get_by_project_id.call_count == 1

