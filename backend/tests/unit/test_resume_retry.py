import asyncio
from datetime import UTC, datetime, timedelta
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
from app.services.parsing_service import (
    DocumentNotParseableException,
    DocumentParseFailedException,
    ParsingService,
)
from app.services.project_service import ProjectNotFoundException


def _build_test_document(
    project_id,
    document_id=None,
    status=ProcessingStatusEnum.FAILED,
    stage=ProcessingStageEnum.FAILED,
    deleted_at=None,
    doc_type=DocumentTypeEnum.RESUME,
    updated_at=None,
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
    doc.updated_at = updated_at
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
    mock_repository.update_processing = AsyncMock()

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
    """If a stage fails during retry, the error propagates, status is persisted as FAILED, and lock is freed."""
    project_id = uuid4()
    doc = _build_test_document(project_id, status=ProcessingStatusEnum.FAILED)
    service, repo = _build_service(doc)

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
    # Transaction rollback must have been executed
    repo.session.rollback.assert_called_once()
    # Failed status and error message must have been persisted
    repo.update_processing.assert_called_once_with(
        doc.id,
        ProcessingStage.FAILED,
        ProcessingStatus.FAILED,
        error_message="Document parsing failed.",
    )


@pytest.mark.asyncio
async def test_retry_resume_rejects_genuinely_active_retry_without_corrupting_status():
    """An IN_PROGRESS document updated recently represents a genuinely active task and is rejected with 409 without modifying status."""
    project_id = uuid4()
    doc = _build_test_document(
        project_id,
        status=ProcessingStatusEnum.IN_PROGRESS,
        stage=ProcessingStageEnum.PARSING,
        updated_at=datetime.now(UTC),
    )
    service, repo = _build_service(doc)

    with pytest.raises(DocumentRetryInProgressException) as exc_info:
        await service.retry_resume(project_id, doc.id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "DOCUMENT_RETRY_IN_PROGRESS"
    # Ensure downstream pipeline was NOT touched and no status was overwritten
    repo.cleanup_pipeline_data.assert_not_called()
    repo.update_processing.assert_not_called()
    assert doc.id not in _active_retries


@pytest.mark.asyncio
async def test_retry_resume_recovers_stale_in_progress_document():
    """An IN_PROGRESS document with a stale timestamp is safely recovered and retried."""
    project_id = uuid4()
    doc = _build_test_document(
        project_id,
        status=ProcessingStatusEnum.IN_PROGRESS,
        stage=ProcessingStageEnum.PARSING,
        updated_at=datetime.now(UTC) - timedelta(seconds=600),
    )
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
    assert result.processing_status == ProcessingStatus.COMPLETED
    repo.cleanup_pipeline_data.assert_called_once()
    mock_parser.parse_document.assert_called_once_with(doc.id, force=True)
    assert doc.id not in _active_retries


@pytest.mark.asyncio
async def test_recover_stale_document_method():
    """Test recover_stale_document resets stale in-progress document and ignores fresh active document."""
    project_id = uuid4()
    stale_doc = _build_test_document(
        project_id,
        status=ProcessingStatusEnum.IN_PROGRESS,
        updated_at=datetime.now(UTC) - timedelta(seconds=600),
    )
    service, repo = _build_service(stale_doc)

    recovered = await service.recover_stale_document(project_id, stale_doc.id)
    assert recovered is True
    repo.update_processing.assert_called_once_with(
        stale_doc.id,
        ProcessingStage.FAILED,
        ProcessingStatus.FAILED,
        error_message="Processing timed out or was interrupted.",
    )

    # Active fresh document should NOT be recovered
    fresh_doc = _build_test_document(
        project_id,
        status=ProcessingStatusEnum.IN_PROGRESS,
        updated_at=datetime.now(UTC),
    )
    service_fresh, repo_fresh = _build_service(fresh_doc)
    recovered_fresh = await service_fresh.recover_stale_document(project_id, fresh_doc.id)
    assert recovered_fresh is False
    repo_fresh.update_processing.assert_not_called()


@pytest.mark.asyncio
async def test_force_parsing_allows_in_progress_status(tmp_path):
    """force=True allows parsing a document in IN_PROGRESS status, while force=False rejects it."""
    file_path = tmp_path / "resume.txt"
    file_path.write_text("Senior Software Engineer", encoding="utf-8")

    doc = MagicMock(spec=DocumentModel)
    doc.id = uuid4()
    doc.document_type = DocumentTypeEnum.RESUME
    doc.original_filename = "resume.txt"
    doc.file_path = str(file_path)
    doc.mime_type = "text/plain"
    doc.processing_status = ProcessingStatusEnum.IN_PROGRESS
    doc.processing_stage = ProcessingStageEnum.PARSING
    doc.metadata_json = {}

    parsed_doc = MagicMock(spec=DocumentModel)
    parsed_doc.processing_status = ProcessingStatusEnum.PARSED
    parsed_doc.processing_stage = ProcessingStageEnum.PARSING

    doc_repo = AsyncMock()
    doc_repo.get_document = AsyncMock(return_value=doc)
    doc_repo.update_status = AsyncMock(return_value=parsed_doc)
    doc_repo.update_processing = AsyncMock()

    parsed_repo = AsyncMock()
    parsed_repo.get_by_document_id = AsyncMock(return_value=None)
    parsed_repo.create_or_update = AsyncMock()

    storage = MagicMock()
    storage.resolve_file = MagicMock(return_value=file_path)

    service = ParsingService(
        document_repository=doc_repo,
        parsed_repository=parsed_repo,
        storage=storage,
    )

    # When force=False, IN_PROGRESS is rejected
    with pytest.raises(DocumentNotParseableException):
        await service.parse_document(doc.id, force=False)

    # When force=True, IN_PROGRESS is accepted and parsed
    result = await service.parse_document(doc.id, force=True)
    assert result.document_id == doc.id
    assert result.processing_status == ProcessingStatus.PARSED


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

