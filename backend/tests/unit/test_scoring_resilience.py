from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.models.document import DocumentModel, DocumentTypeEnum, ProcessingStatusEnum
from app.services.scoring_service import (
    NoEligibleResumesException,
    ScoringEngineFacade,
    ScoringFailedException,
)


def _build_facade(resumes, norm_models, ext_models, upsert_score_side_effect=None):
    for r in resumes:
        if isinstance(r, DocumentModel) and not getattr(r, "metadata_json", None):
            r.metadata_json = {"verification": {"verification_status": "VERIFIED"}}
    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(return_value=MagicMock())

    mock_documents = MagicMock()
    mock_documents.list_resumes_by_project = AsyncMock(return_value=(resumes, len(resumes)))
    mock_documents.get_job_description_by_project = AsyncMock(return_value=MagicMock(id=uuid4()))

    mock_normalizations = MagicMock()
    mock_normalizations.get_job_description_by_document_id = AsyncMock(
        return_value=MagicMock(skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    )
    mock_normalizations.get_resumes_by_document_ids = AsyncMock(return_value=norm_models)
    mock_normalizations.get_resume_by_document_id = AsyncMock()

    mock_extractions = MagicMock()
    mock_extractions.get_resumes_by_document_ids = AsyncMock(return_value=ext_models)
    mock_extractions.get_resume_by_document_id = AsyncMock()

    mock_scores = MagicMock()
    if upsert_score_side_effect is None:
        mock_scores.upsert_score = AsyncMock(
            side_effect=lambda data, *args, **kwargs: MagicMock(id=uuid4(), **data.model_dump())
        )
    else:
        mock_scores.upsert_score = AsyncMock(side_effect=upsert_score_side_effect)

    facade = ScoringEngineFacade(
        projects=mock_projects,
        documents=mock_documents,
        normalizations=mock_normalizations,
        extractions=mock_extractions,
        scores=mock_scores,
    )
    facade.hybrid_matching.match = AsyncMock(side_effect=RuntimeError("hybrid matching disabled in test"))
    return facade


@pytest.mark.asyncio
async def test_score_project_mixed_valid_and_failed_resumes():
    """Valid resumes are scored while failed or incomplete resumes are excluded."""
    project_id = uuid4()
    doc1 = DocumentModel(
        id=uuid4(),
        project_id=project_id,
        document_type=DocumentTypeEnum.RESUME,
        processing_status=ProcessingStatusEnum.COMPLETED,
    )
    doc2 = DocumentModel(
        id=uuid4(),
        project_id=project_id,
        document_type=DocumentTypeEnum.RESUME,
        processing_status=ProcessingStatusEnum.FAILED,
    )
    doc3 = DocumentModel(
        id=uuid4(),
        project_id=project_id,
        document_type=DocumentTypeEnum.RESUME,
        processing_status=ProcessingStatusEnum.UPLOADED,
    )

    norm1 = MagicMock(document_id=doc1.id, experience=[], skills=[], job_titles=[], education=[])
    ext1 = MagicMock(document_id=doc1.id, projects=[], candidate_name="Candidate One")

    facade = _build_facade(
        resumes=[doc1, doc2, doc3],
        norm_models=[norm1],
        ext_models=[ext1],
    )

    result = await facade.score_project(project_id)

    assert result.total_evaluated == 1
    assert len(result.scores) == 1
    assert result.scores[0].document_id == doc1.id


@pytest.mark.asyncio
async def test_score_project_individual_scoring_failure_does_not_block_others():
    """A failure during scoring of one candidate does not block other valid candidates."""
    project_id = uuid4()
    doc1 = DocumentModel(
        id=uuid4(),
        project_id=project_id,
        document_type=DocumentTypeEnum.RESUME,
        processing_status=ProcessingStatusEnum.COMPLETED,
    )
    doc2 = DocumentModel(
        id=uuid4(),
        project_id=project_id,
        document_type=DocumentTypeEnum.RESUME,
        processing_status=ProcessingStatusEnum.COMPLETED,
    )

    norm1 = MagicMock(document_id=doc1.id, experience=[], skills=[], job_titles=[], education=[])
    norm2 = MagicMock(document_id=doc2.id, experience=[], skills=[], job_titles=[], education=[])
    ext1 = MagicMock(document_id=doc1.id, projects=[], candidate_name="Candidate One")
    ext2 = MagicMock(document_id=doc2.id, projects=[], candidate_name="Candidate Two")

    def _upsert_score_mock(data, *args, **kwargs):
        if data.document_id == doc2.id:
            raise RuntimeError("Database error during candidate two score upsert")
        return MagicMock(id=uuid4(), **data.model_dump())

    facade = _build_facade(
        resumes=[doc1, doc2],
        norm_models=[norm1, norm2],
        ext_models=[ext1, ext2],
        upsert_score_side_effect=_upsert_score_mock,
    )

    result = await facade.score_project(project_id)

    # doc1 succeeded, doc2 failed; doc1 is preserved and returned
    assert result.total_evaluated == 1
    assert len(result.scores) == 1
    assert result.scores[0].document_id == doc1.id


@pytest.mark.asyncio
async def test_score_project_zero_eligible_resumes_raises_error():
    """When all resumes in a project are failed or incomplete, NoEligibleResumesException is raised."""
    project_id = uuid4()
    doc1 = DocumentModel(
        id=uuid4(),
        project_id=project_id,
        document_type=DocumentTypeEnum.RESUME,
        processing_status=ProcessingStatusEnum.FAILED,
    )
    doc2 = DocumentModel(
        id=uuid4(),
        project_id=project_id,
        document_type=DocumentTypeEnum.RESUME,
        processing_status=ProcessingStatusEnum.UPLOADED,
    )

    facade = _build_facade(
        resumes=[doc1, doc2],
        norm_models=[],
        ext_models=[],
    )

    with pytest.raises(NoEligibleResumesException) as exc_info:
        await facade.score_project(project_id)

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "NO_ELIGIBLE_RESUMES"


@pytest.mark.asyncio
async def test_score_project_empty_resumes_raises_error():
    """When a project has zero resumes uploaded, NoEligibleResumesException is raised."""
    project_id = uuid4()
    facade = _build_facade(
        resumes=[],
        norm_models=[],
        ext_models=[],
    )

    with pytest.raises(NoEligibleResumesException) as exc_info:
        await facade.score_project(project_id)

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "NO_ELIGIBLE_RESUMES"


@pytest.mark.asyncio
async def test_score_project_all_eligible_candidates_fail_raises_error():
    """When all eligible candidates fail during scoring execution, an error is raised."""
    project_id = uuid4()
    doc1 = DocumentModel(
        id=uuid4(),
        project_id=project_id,
        document_type=DocumentTypeEnum.RESUME,
        processing_status=ProcessingStatusEnum.COMPLETED,
    )

    norm1 = MagicMock(document_id=doc1.id, experience=[], skills=[], job_titles=[], education=[])
    ext1 = MagicMock(document_id=doc1.id, projects=[], candidate_name="Candidate One")

    def _upsert_score_mock(data, *args, **kwargs):
        raise RuntimeError("Fatal write error")

    facade = _build_facade(
        resumes=[doc1],
        norm_models=[norm1],
        ext_models=[ext1],
        upsert_score_side_effect=_upsert_score_mock,
    )

    with pytest.raises(ScoringFailedException):
        await facade.score_project(project_id)
