from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.models.document import DocumentModel, DocumentTypeEnum
from app.services.scoring_service import ScoringEngineFacade


@pytest.mark.asyncio
async def test_score_project_uses_bulk_loading() -> None:
    project_id = uuid4()
    doc1 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)
    doc2 = DocumentModel(id=uuid4(), project_id=project_id, document_type=DocumentTypeEnum.RESUME)

    # Repositories
    mock_projects = MagicMock()
    mock_projects.get_by_id = AsyncMock(return_value=MagicMock())

    mock_documents = MagicMock()
    mock_documents.list_resumes_by_project = AsyncMock(return_value=([doc1, doc2], 2))
    mock_documents.get_job_description_by_project = AsyncMock(return_value=MagicMock(id=uuid4()))

    norm1 = MagicMock(document_id=doc1.id, experience=[], skills=[], job_titles=[], education=[])
    norm2 = MagicMock(document_id=doc2.id, experience=[], skills=[], job_titles=[], education=[])
    mock_normalizations = MagicMock()
    mock_normalizations.get_job_description_by_document_id = AsyncMock(
        return_value=MagicMock(skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    )
    mock_normalizations.get_resumes_by_document_ids = AsyncMock(return_value=[norm1, norm2])
    mock_normalizations.get_resume_by_document_id = AsyncMock()

    ext1 = MagicMock(document_id=doc1.id, projects=[], candidate_name="Candidate One")
    ext2 = MagicMock(document_id=doc2.id, projects=[], candidate_name="Candidate Two")
    mock_extractions = MagicMock()
    mock_extractions.get_resumes_by_document_ids = AsyncMock(return_value=[ext1, ext2])
    mock_extractions.get_resume_by_document_id = AsyncMock()

    mock_scores = MagicMock()
    mock_scores.upsert_score = AsyncMock(side_effect=lambda data, *args, **kwargs: MagicMock(id=uuid4(), **data.model_dump()))

    facade = ScoringEngineFacade(
        projects=mock_projects,
        documents=mock_documents,
        normalizations=mock_normalizations,
        extractions=mock_extractions,
        scores=mock_scores,
    )
    facade.hybrid_matching.match = AsyncMock(side_effect=RuntimeError("hybrid unavailable"))

    result = await facade.score_project(project_id)

    assert result.total_evaluated == 2
    mock_normalizations.get_resumes_by_document_ids.assert_called_once_with([doc1.id, doc2.id])
    mock_extractions.get_resumes_by_document_ids.assert_called_once_with([doc1.id, doc2.id])

    # Per-document single getters MUST NOT be called during score_project
    mock_normalizations.get_resume_by_document_id.assert_not_called()
    mock_extractions.get_resume_by_document_id.assert_not_called()
    assert all(score.match_verdicts == [] for score in result.scores)
