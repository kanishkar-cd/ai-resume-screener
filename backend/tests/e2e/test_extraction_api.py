from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.extraction import get_extraction_service
from app.main import app
from app.schemas.document import DocumentType, ProcessingStage
from app.schemas.extracted_info import ExtractDocumentResponse, ExtractedResumeRead
from app.services.extraction_service import ExtractedDataNotFoundException, ParsedTextNotFoundException


class FakeExtractionService:
    def __init__(self) -> None:
        self.document_id = uuid4()

    async def extract_document_data(self, document_id: UUID) -> ExtractDocumentResponse:
        if document_id != self.document_id:
            raise ParsedTextNotFoundException()
        return ExtractDocumentResponse(
            document_id=document_id, document_type=DocumentType.RESUME,
            processing_stage=ProcessingStage.COMPLETED,
            message="Information extracted successfully.",
        )

    async def get_extracted_data(self, document_id: UUID) -> ExtractedResumeRead:
        if document_id != self.document_id:
            raise ExtractedDataNotFoundException()
        now = datetime.now(UTC)
        return ExtractedResumeRead(
            id=uuid4(), document_id=document_id, candidate_name="Jane Doe",
            email="jane@example.com", skills=["Python"],
            confidence_scores={"candidate_name": 0.85, "email": 0.98},
            created_at=now, updated_at=now,
        )


@pytest.mark.asyncio
async def test_extract_and_get_extracted_api(async_client: httpx.AsyncClient) -> None:
    service = FakeExtractionService()
    app.dependency_overrides[get_extraction_service] = lambda: service
    triggered = await async_client.post(f"/api/v1/documents/{service.document_id}/extract")
    assert triggered.status_code == 200
    assert triggered.json()["data"]["processing_stage"] == "COMPLETED"
    fetched = await async_client.get(f"/api/v1/documents/{service.document_id}/extracted")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["candidate_name"] == "Jane Doe"
    assert fetched.json()["data"]["confidence_scores"]["email"] == 0.98


@pytest.mark.asyncio
async def test_extraction_api_negative_contracts(async_client: httpx.AsyncClient) -> None:
    service = FakeExtractionService()
    app.dependency_overrides[get_extraction_service] = lambda: service
    missing_id = uuid4()
    unparsed = await async_client.post(f"/api/v1/documents/{missing_id}/extract")
    assert unparsed.status_code == 400
    assert unparsed.json()["error"]["code"] == "PARSED_TEXT_NOT_FOUND"
    missing = await async_client.get(f"/api/v1/documents/{missing_id}/extracted")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "EXTRACTED_DATA_NOT_FOUND"
