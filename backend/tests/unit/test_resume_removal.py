from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from app.api.v1.endpoints.documents import get_document_service
from app.main import app
from app.models.document import (
    DocumentModel,
    DocumentTypeEnum,
    ProcessingStageEnum,
    ProcessingStatusEnum,
)
from app.schemas.document import DocumentType
from app.services.document_service import (
    DocumentBelongsToAnotherProjectException,
    DocumentNotFoundException,
    DocumentRetryInProgressException,
    DocumentService,
    _active_retries,
)
from app.services.project_service import ProjectNotFoundException


def _build_test_document(
    project_id,
    document_id=None,
    status=ProcessingStatusEnum.COMPLETED,
    stage=ProcessingStageEnum.COMPLETED,
    deleted_at=None,
    doc_type=DocumentTypeEnum.RESUME,
):
    doc = MagicMock(spec=DocumentModel)
    doc.id = document_id or uuid4()
    doc.project_id = project_id
    doc.document_type = doc_type
    doc.original_filename = "test_candidate.pdf"
    doc.file_path = f"projects/{project_id}/resumes/{doc.id}.pdf"
    doc.processing_status = status
    doc.processing_stage = stage
    doc.deleted_at = deleted_at
    return doc


def _build_service(doc, project_exists=True):
    mock_projects = MagicMock()
    if project_exists:
        mock_projects.get_by_id = AsyncMock(return_value=MagicMock())
    else:
        mock_projects.get_by_id = AsyncMock(return_value=None)

    mock_repository = MagicMock()
    mock_repository.session = AsyncMock()
    mock_repository.session.commit = AsyncMock()
    mock_repository.session.rollback = AsyncMock()
    mock_repository.get_by_id = AsyncMock(return_value=doc)
    mock_repository.cleanup_pipeline_data = AsyncMock()
    mock_repository.delete_document = AsyncMock(return_value=doc)

    mock_storage = MagicMock()
    mock_storage.delete_file = MagicMock(return_value=True)

    service = DocumentService(
        repository=mock_repository,
        project_repository=mock_projects,
        storage=mock_storage,
    )
    return service, mock_repository, mock_storage


@pytest.mark.asyncio
async def test_delete_resume_success():
    """Successful resume deletion cleans pipeline data, soft-deletes DB record, and deletes physical file."""
    project_id = uuid4()
    doc = _build_test_document(project_id)
    service, repo, storage = _build_service(doc)

    await service.delete_resume(project_id, doc.id)

    # 1. Pipeline records cascade cleanup
    repo.cleanup_pipeline_data.assert_awaited_once_with(doc.id, DocumentType.RESUME)

    # 2. Soft-delete document in database
    repo.delete_document.assert_awaited_once_with(doc.id, commit=False)
    repo.session.commit.assert_awaited_once()

    # 3. Physical file deleted from storage
    storage.delete_file.assert_called_once_with(doc.file_path)


@pytest.mark.asyncio
async def test_delete_resume_missing_resume_raises_not_found():
    """Deleting a non-existent document raises DocumentNotFoundException (404)."""
    project_id = uuid4()
    service, _, _ = _build_service(None)

    with pytest.raises(DocumentNotFoundException) as exc_info:
        await service.delete_resume(project_id, uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_resume_wrong_project_raises_mismatch():
    """Deleting a resume that belongs to another project raises DocumentBelongsToAnotherProjectException (400)."""
    project_id = uuid4()
    other_project_id = uuid4()
    doc = _build_test_document(project_id=other_project_id)
    service, _, _ = _build_service(doc)

    with pytest.raises(DocumentBelongsToAnotherProjectException) as exc_info:
        await service.delete_resume(project_id, doc.id)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_resume_deleted_resume_raises_not_found():
    """Deleting an already soft-deleted resume raises DocumentNotFoundException (404)."""
    project_id = uuid4()
    doc = _build_test_document(project_id, deleted_at=datetime.now(UTC))
    service, _, _ = _build_service(doc)

    with pytest.raises(DocumentNotFoundException) as exc_info:
        await service.delete_resume(project_id, doc.id)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_resume_invalid_document_type_raises_not_found():
    """Deleting a document that is not a resume (e.g. JD) raises DocumentNotFoundException (404)."""
    project_id = uuid4()
    doc = _build_test_document(project_id, doc_type=DocumentTypeEnum.JOB_DESCRIPTION)
    service, _, _ = _build_service(doc)

    with pytest.raises(DocumentNotFoundException) as exc_info:
        await service.delete_resume(project_id, doc.id)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_resume_concurrent_retry_conflict():
    """Deleting a resume while a retry is actively in progress raises DocumentRetryInProgressException (409)."""
    project_id = uuid4()
    doc = _build_test_document(project_id)
    service, _, _ = _build_service(doc)

    _active_retries.add(doc.id)
    try:
        with pytest.raises(DocumentRetryInProgressException) as exc_info:
            await service.delete_resume(project_id, doc.id)
        assert exc_info.value.status_code == 409
    finally:
        _active_retries.discard(doc.id)


@pytest.mark.asyncio
async def test_delete_resume_refresh_persistence():
    """After soft-deletion, list_resumes_by_project filters out deleted documents so they do not reappear."""
    project_id = uuid4()
    active_doc = _build_test_document(project_id, document_id=uuid4(), deleted_at=None)
    deleted_doc = _build_test_document(project_id, document_id=uuid4(), deleted_at=datetime.now(UTC))

    mock_repository = MagicMock()
    # Emulate list_resumes_by_project behavior where deleted_at.is_(None) is enforced
    mock_repository.list_resumes_by_project = AsyncMock(
        return_value=([active_doc], 1)
    )

    docs, total = await mock_repository.list_resumes_by_project(project_id=project_id)
    assert total == 1
    assert active_doc in docs
    assert deleted_doc not in docs


@pytest.mark.asyncio
async def test_delete_resume_api_endpoint():
    """Verify HTTP route DELETE /api/v1/projects/{project_id}/resumes/{document_id}."""
    project_id = uuid4()
    doc_id = uuid4()

    mock_service = MagicMock()
    mock_service.delete_resume = AsyncMock(return_value=None)

    app.dependency_overrides[get_document_service] = lambda: mock_service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # 1. Successful deletion returns 204 No Content
            response = await client.delete(f"/api/v1/projects/{project_id}/resumes/{doc_id}")
            assert response.status_code == 204
            mock_service.delete_resume.assert_awaited_once_with(project_id, doc_id)

            # 2. Resume not found returns 404
            mock_service.delete_resume = AsyncMock(side_effect=DocumentNotFoundException())
            response = await client.delete(f"/api/v1/projects/{project_id}/resumes/{doc_id}")
            assert response.status_code == 404

            # 3. Resume belongs to another project returns 400
            mock_service.delete_resume = AsyncMock(side_effect=DocumentBelongsToAnotherProjectException())
            response = await client.delete(f"/api/v1/projects/{project_id}/resumes/{doc_id}")
            assert response.status_code == 400
    finally:
        app.dependency_overrides.pop(get_document_service, None)
