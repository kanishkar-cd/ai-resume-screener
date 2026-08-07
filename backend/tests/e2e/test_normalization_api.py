from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.normalization import get_normalization_service
from app.main import app
from app.schemas.document import DocumentType, ProcessingStage
from app.schemas.normalized_info import (
    NormalizationMetadata, NormalizeDocumentResponse, NormalizedResumeRead,
)
from app.services.normalization_service import ExtractedDataNotFoundException, NormalizedDataNotFoundException


class FakeNormalizationService:
    def __init__(self) -> None: self.document_id = uuid4()
    async def normalize_document_data(self, document_id: UUID) -> NormalizeDocumentResponse:
        if document_id != self.document_id: raise ExtractedDataNotFoundException()
        return NormalizeDocumentResponse(document_id=document_id, document_type=DocumentType.RESUME, processing_stage=ProcessingStage.COMPLETED, ruleset_version="1.0.0", message="Document data normalized successfully.")
    async def get_normalized_data(self, document_id: UUID) -> NormalizedResumeRead:
        if document_id != self.document_id: raise NormalizedDataNotFoundException()
        now = datetime.now(UTC)
        return NormalizedResumeRead(
            id=uuid4(), document_id=document_id, extracted_resume_id=uuid4(),
            skills=["Python"], email="jane@example.com", ruleset_version="1.0.0",
            normalization_metadata=NormalizationMetadata(ruleset_version="1.0.0", normalized_at=now, field_confidence={"skills": 0.95}),
            created_at=now, updated_at=now,
        )


@pytest.mark.asyncio
async def test_normalize_and_get_normalized_api(async_client: httpx.AsyncClient) -> None:
    service = FakeNormalizationService()
    app.dependency_overrides[get_normalization_service] = lambda: service
    posted = await async_client.post(f"/api/v1/documents/{service.document_id}/normalize")
    assert posted.status_code == 200
    assert posted.json()["data"]["ruleset_version"] == "1.0.0"
    fetched = await async_client.get(f"/api/v1/documents/{service.document_id}/normalized")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["skills"] == ["Python"]
    assert fetched.json()["data"]["normalization_metadata"]["field_confidence"]["skills"] == 0.95


@pytest.mark.asyncio
async def test_normalization_api_negative_contracts(async_client: httpx.AsyncClient) -> None:
    service = FakeNormalizationService()
    app.dependency_overrides[get_normalization_service] = lambda: service
    missing = uuid4()
    response = await async_client.post(f"/api/v1/documents/{missing}/normalize")
    assert response.status_code == 400 and response.json()["error"]["code"] == "EXTRACTED_DATA_NOT_FOUND"
    response = await async_client.get(f"/api/v1/documents/{missing}/normalized")
    assert response.status_code == 404 and response.json()["error"]["code"] == "NORMALIZED_DATA_NOT_FOUND"
    assert (await async_client.get("/api/v1/documents/not-a-uuid/normalized")).status_code == 422


def test_stage4_openapi_paths_preserve_prior_stages() -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/api/v1/documents/{document_id}/parse", "/api/v1/documents/{document_id}/extract",
        "/api/v1/documents/{document_id}/normalize", "/api/v1/documents/{document_id}/normalized",
    ):
        assert path in paths
