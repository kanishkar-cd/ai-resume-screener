from datetime import UTC, datetime
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.models.document import (
    DocumentTypeEnum,
    ProcessingStageEnum,
    ProcessingStatusEnum,
)
from app.schemas.document import DocumentType, SortOrder
from app.services.document_service import (
    DocumentFileMissingException,
    DocumentNotFoundException,
    DocumentService,
)
from app.services.project_service import ProjectNotFoundException
from app.services.storage_service import StorageIOException


def document_record() -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        document_type=DocumentTypeEnum.RESUME,
        original_filename="resume.pdf",
        stored_filename=f"{uuid4()}.pdf",
        file_path="stored/resume.pdf",
        file_size_bytes=12,
        mime_type="application/pdf",
        file_hash="a" * 64,
        processing_stage=ProcessingStageEnum.UPLOAD,
        processing_status=ProcessingStatusEnum.UPLOADED,
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


def service_fixture() -> tuple[DocumentService, AsyncMock, AsyncMock, Mock]:
    repository = AsyncMock()
    repository.session = AsyncMock()
    projects = AsyncMock()
    projects.get_by_id.return_value = SimpleNamespace(id=uuid4())
    storage = Mock()
    return DocumentService(repository, projects, storage), repository, projects, storage


@pytest.mark.asyncio
async def test_list_returns_paginated_documents() -> None:
    service, repository, _, _ = service_fixture()
    repository.list_documents.return_value = ([document_record()], 1)

    response = await service.list_documents(
        None, None, None, " resume ", 1, 20, SortOrder.DESC
    )

    assert response.total == 1
    assert response.total_pages == 1
    assert response.items[0].original_filename == "resume.pdf"
    assert repository.list_documents.await_args.kwargs["search"] == "resume"


@pytest.mark.asyncio
async def test_project_filter_requires_active_project() -> None:
    service, _, projects, _ = service_fixture()
    projects.get_by_id.return_value = None
    with pytest.raises(ProjectNotFoundException):
        await service.list_documents(
            uuid4(), None, None, None, 1, 20, SortOrder.DESC
        )


@pytest.mark.asyncio
async def test_upload_requires_active_project() -> None:
    service, _, projects, storage = service_fixture()
    projects.get_by_id.return_value = None
    file = UploadFile(
        BytesIO(b"plain text"),
        filename="resume.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    with pytest.raises(ProjectNotFoundException):
        await service.upload_document(uuid4(), DocumentType.RESUME, file)
    storage.save_file.assert_not_called()


@pytest.mark.asyncio
async def test_missing_and_deleted_document_returns_not_found() -> None:
    service, repository, _, _ = service_fixture()
    repository.get_document.return_value = None
    with pytest.raises(DocumentNotFoundException):
        await service.get_document(uuid4())


@pytest.mark.asyncio
async def test_download_rejects_missing_physical_file() -> None:
    service, repository, _, storage = service_fixture()
    repository.download_document.return_value = document_record()
    storage.resolve_file.return_value = None
    with pytest.raises(DocumentFileMissingException):
        await service.download_document(uuid4())


@pytest.mark.asyncio
async def test_delete_rolls_back_when_storage_deletion_fails() -> None:
    service, repository, _, storage = service_fixture()
    record = document_record()
    repository.get_document.return_value = record
    repository.delete_document.return_value = record
    storage.resolve_file.return_value = Path(record.file_path)
    storage.delete_file.side_effect = StorageIOException()

    with pytest.raises(StorageIOException):
        await service.delete_document(record.id)

    repository.session.rollback.assert_awaited_once()
    repository.session.commit.assert_not_awaited()
