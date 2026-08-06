from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.documents import get_document_service
from app.main import app
from app.schemas.document import (
    DocumentType,
    DocumentPaginatedResponse,
    DocumentRead,
    DocumentUploadRead,
    ProcessingStage,
    ProcessingStatus,
)
from app.services.document_service import DocumentDownload, DocumentNotFoundException


class FakeDocumentService:
    async def upload_document(
        self, project_id: UUID, document_type: DocumentType, file: object
    ) -> DocumentUploadRead:
        return DocumentUploadRead(
            document_id=uuid4(),
            project_id=project_id,
            document_type=document_type,
            filename="resume.pdf",
            processing_stage=ProcessingStage.INGESTION,
            processing_status=ProcessingStatus.UPLOADED,
        )


class FakeDocumentCrudService:
    def __init__(self, path: Path) -> None:
        self.path = path
        now = datetime.now(UTC)
        self.document = DocumentRead(
            id=uuid4(),
            project_id=uuid4(),
            document_type=DocumentType.RESUME,
            original_filename="resume.txt",
            file_size_bytes=len(path.read_bytes()),
            mime_type="text/plain",
            file_hash="a" * 64,
            processing_stage=ProcessingStage.INGESTION,
            processing_status=ProcessingStatus.UPLOADED,
            metadata_json={},
            created_at=now,
            updated_at=now,
        )
        self.deleted = False

    async def list_documents(self, *args: object) -> DocumentPaginatedResponse:
        items = [] if self.deleted else [self.document]
        return DocumentPaginatedResponse(
            items=items,
            total=len(items),
            page=1,
            page_size=20,
            total_pages=1 if items else 0,
        )

    async def get_document(self, document_id: UUID) -> DocumentRead:
        if self.deleted or document_id != self.document.id:
            raise DocumentNotFoundException()
        return self.document

    async def download_document(self, document_id: UUID) -> DocumentDownload:
        await self.get_document(document_id)
        return DocumentDownload(self.path, "resume.txt", "text/plain")

    async def delete_document(self, document_id: UUID) -> None:
        await self.get_document(document_id)
        self.deleted = True


@pytest.mark.asyncio
async def test_document_upload_multipart_contract(
    async_client: httpx.AsyncClient,
) -> None:
    app.dependency_overrides[get_document_service] = lambda: FakeDocumentService()
    project_id = uuid4()
    response = await async_client.post(
        "/api/v1/documents/upload",
        data={"project_id": str(project_id), "document_type": "RESUME"},
        files={"file": ("resume.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["data"] == {
        "document_id": response.json()["data"]["document_id"],
        "project_id": str(project_id),
        "document_type": "RESUME",
        "filename": "resume.pdf",
        "processing_stage": "INGESTION",
        "processing_status": "UPLOADED",
    }


@pytest.mark.asyncio
async def test_document_list_get_download_delete_contracts(
    async_client: httpx.AsyncClient, tmp_path: Path
) -> None:
    path = tmp_path / "resume.txt"
    path.write_bytes(b"resume content")
    service = FakeDocumentCrudService(path)
    app.dependency_overrides[get_document_service] = lambda: service
    document_id = service.document.id

    listed = await async_client.get(
        "/api/v1/documents?search=resume&page=1&page_size=20&sort_by=created_at&sort_order=desc"
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1

    fetched = await async_client.get(f"/api/v1/documents/{document_id}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["original_filename"] == "resume.txt"
    assert "file_path" not in fetched.json()["data"]

    downloaded = await async_client.get(
        f"/api/v1/documents/{document_id}/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"resume content"
    assert "resume.txt" in downloaded.headers["content-disposition"]

    deleted = await async_client.delete(f"/api/v1/documents/{document_id}")
    assert deleted.status_code == 204

    missing = await async_client.get(f"/api/v1/documents/{document_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"

    invalid = await async_client.get("/api/v1/documents/not-a-uuid")
    assert invalid.status_code == 422
