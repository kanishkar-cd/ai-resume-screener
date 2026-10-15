import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from app.api.v1.endpoints.documents import get_document_service
from app.core.exceptions import AppException
from app.main import app
from app.models.document import (
    DocumentModel,
    DocumentTypeEnum,
    ProcessingStageEnum,
    ProcessingStatusEnum,
)
from app.schemas.document import ProcessingStage, ProcessingStatus, ResumeRetryRead
from app.services.document_service import (
    DocumentBelongsToAnotherProjectException,
    DocumentNotFoundException,
    DocumentNotRetryableException,
    DocumentRetryInProgressException,
    DocumentService,
    _active_retries,
)
from app.services.parsing_service import DocumentParseFailedException
from app.services.project_service import ProjectNotFoundException


def _build_test_document(
    project_id,
    document_id=None,
    status=ProcessingStatusEnum.FAILED,
    stage=ProcessingStageEnum.FAILED,
    deleted_at=None,
    doc_type=DocumentTypeEnum.RESUME,
):
    doc = MagicMock(spec=DocumentModel)
    doc.id = document_id or uuid4()
    doc.project_id = project_id
    doc.document_type = doc_type
    doc.original_filename = "candidate_resume.pdf"
    doc.file_path = f"projects/{project_id}/resumes/{doc.id}.pdf"
    doc.processing_status = status
    doc.processing_stage = stage
    doc.deleted_at = deleted_at
    doc.error_message = "Previous parse error"
    return doc


def _build_service(doc, project_exists=True):
    mock_projects = MagicMock()
    if project_exists:
        mock_projects.get_by_id = AsyncMock(return_value=MagicMock())
    else:
        mock_projects.get_by_id = AsyncMock(return_value=None)

    mock_repository = MagicMock()
    mock_repository.session = AsyncMock()
    mock_repository.get_by_id = AsyncMock(return_value=doc)
    mock_repository.cleanup_pipeline_data = AsyncMock()

    async def _mock_refresh(target):
        target.processing_status = ProcessingStatusEnum.COMPLETED
        target.processing_stage = ProcessingStageEnum.COMPLETED

    mock_repository.session.refresh = AsyncMock(side_effect=_mock_refresh)
    mock_repository.session.commit = AsyncMock()
    mock_repository.session.rollback = AsyncMock()

    mock_storage = MagicMock()
    mock_storage.file_exists = MagicMock(return_value=True)

    service = DocumentService(
        repository=mock_repository,
        project_repository=mock_projects,
        storage=mock_storage,
    )
    return service, mock_repository


@pytest.mark.asyncio
async def test_retry_resume_success():
    """A failed resume is safely cleaned, re-processed through all 3 stages, and marked completed."""
    project_id = uuid4()
    doc = _build_test_document(project_id, status=ProcessingStatusEnum.FAILED, stage=ProcessingStageEnum.FAILED)
    service, repo = _build_service(doc)

    mock_parser = MagicMock()
    mock_parser.parse_document = AsyncMock(return_value=MagicMock())
    mock_extractor = MagicMock()
    mock_extractor.extract_document_data = AsyncMock(return_value=MagicMock())
    mock_normalizer = MagicMock()
    mock_normalizer.normalize_document_data = AsyncMock(return_value=MagicMock())

    result = await service.retry_resume(
        project_id,
        doc.id,
        parsing_service=mock_parser,
        extraction_service=mock_extractor,
        normalization_service=mock_normalizer,
    )

    assert result.document_id == doc.id
    assert result.project_id == project_id
    assert result.processing_status == ProcessingStatus.COMPLETED
    assert result.processing_stage == ProcessingStage.COMPLETED

    # Verify downstream records cleaned up and stages executed with force=True
    repo.cleanup_pipeline_data.assert_called_once()
    mock_parser.parse_document.assert_called_once_with(doc.id, force=True)
    mock_extractor.extract_document_data.assert_called_once_with(doc.id, force=True)
    mock_normalizer.normalize_document_data.assert_called_once_with(doc.id, force=True)


@pytest.mark.asyncio
async def test_retry_resume_missing_resume_raises_not_found():
    """Retry on a non-existent document ID raises DocumentNotFoundException."""
    project_id = uuid4()
    service, _ = _build_service(doc=None)

    with pytest.raises(DocumentNotFoundException):
        await service.retry_resume(project_id, uuid4())


@pytest.mark.asyncio
async def test_retry_resume_wrong_project_raises_mismatch():
    """Retry on a resume belonging to a different project raises DocumentBelongsToAnotherProjectException."""
    project_id = uuid4()
    other_project_id = uuid4()
    doc = _build_test_document(other_project_id)
    service, _ = _build_service(doc)

    with pytest.raises(DocumentBelongsToAnotherProjectException):
        await service.retry_resume(project_id, doc.id)


@pytest.mark.asyncio
async def test_retry_resume_deleted_resume_raises_not_found():
    """Retry on a soft-deleted resume raises DocumentNotFoundException."""
    project_id = uuid4()
    doc = _build_test_document(project_id, deleted_at=datetime.now(UTC))
    service, _ = _build_service(doc)

    with pytest.raises(DocumentNotFoundException):
        await service.retry_resume(project_id, doc.id)


@pytest.mark.asyncio
async def test_retry_resume_already_completed_raises_not_retryable():
    """Retry on an already completed resume raises DocumentNotRetryableException (409 Conflict)."""
    project_id = uuid4()
    doc = _build_test_document(
        project_id,
        status=ProcessingStatusEnum.COMPLETED,
        stage=ProcessingStageEnum.COMPLETED,
    )
    service, _ = _build_service(doc)

    with pytest.raises(DocumentNotRetryableException) as exc_info:
        await service.retry_resume(project_id, doc.id)
    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "DOCUMENT_NOT_RETRYABLE"


@pytest.mark.asyncio
async def test_retry_resume_concurrent_retry_raises_conflict():
    """A second concurrent retry on the same resume raises DocumentRetryInProgressException (409 Conflict)."""
    project_id = uuid4()
    doc = _build_test_document(project_id, status=ProcessingStatusEnum.FAILED)
    service, _ = _build_service(doc)

    started_first = asyncio.Event()
    wait_first = asyncio.Event()

    async def _slow_parse(doc_id, force=True):
        started_first.set()
        await wait_first.wait()

    mock_parser = MagicMock()
    mock_parser.parse_document = AsyncMock(side_effect=_slow_parse)

    task1 = asyncio.create_task(
        service.retry_resume(
            project_id,
            doc.id,
            parsing_service=mock_parser,
            extraction_service=MagicMock(extract_document_data=AsyncMock()),
            normalization_service=MagicMock(normalize_document_data=AsyncMock()),
        )
    )

    await started_first.wait()

    # Second concurrent retry should be blocked
    with pytest.raises(DocumentRetryInProgressException) as exc_info:
        await service.retry_resume(project_id, doc.id)
    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "DOCUMENT_RETRY_IN_PROGRESS"

    # Finish task 1
    wait_first.set()
    await task1


@pytest.mark.asyncio
async def test_retry_resume_processing_failure_propagates_and_frees_lock():
    """If a stage fails during retry, the error propagates and the retry lock is freed for subsequent attempts."""
    project_id = uuid4()
    doc = _build_test_document(project_id, status=ProcessingStatusEnum.FAILED)
    service, _ = _build_service(doc)

    mock_parser = MagicMock()
    mock_parser.parse_document = AsyncMock(
        side_effect=DocumentParseFailedException(details={"reason": "Corrupt PDF stream"})
    )

    with pytest.raises(DocumentParseFailedException):
        await service.retry_resume(
            project_id,
            doc.id,
            parsing_service=mock_parser,
            extraction_service=MagicMock(),
            normalization_service=MagicMock(),
        )

    # Concurrency set must be empty after failure
    assert doc.id not in _active_retries


@pytest.mark.asyncio
async def test_retry_resume_api_endpoint():
    """Verify HTTP route POST /api/v1/projects/{project_id}/resumes/{document_id}/retry."""
    project_id = uuid4()
    doc_id = uuid4()

    mock_service = MagicMock()
    mock_service.retry_resume = AsyncMock(
        return_value=ResumeRetryRead(
            document_id=doc_id,
            project_id=project_id,
            filename="candidate.pdf",
            processing_stage=ProcessingStage.COMPLETED,
            processing_status=ProcessingStatus.COMPLETED,
            message="Resume retried and processed successfully.",
        )
    )

    app.dependency_overrides[get_document_service] = lambda: mock_service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # 1. Success case
            response = await client.post(f"/api/v1/projects/{project_id}/resumes/{doc_id}/retry")
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["document_id"] == str(doc_id)
            assert data["processing_status"] == "COMPLETED"

            # 2. Document not found
            mock_service.retry_resume = AsyncMock(side_effect=DocumentNotFoundException())
            response = await client.post(f"/api/v1/projects/{project_id}/resumes/{doc_id}/retry")
            assert response.status_code == 404

            # 3. Already completed conflict
            mock_service.retry_resume = AsyncMock(side_effect=DocumentNotRetryableException())
            response = await client.post(f"/api/v1/projects/{project_id}/resumes/{doc_id}/retry")
            assert response.status_code == 409
    finally:
        app.dependency_overrides.pop(get_document_service, None)
