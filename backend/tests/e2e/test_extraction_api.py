from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.extraction import (
    get_extraction_service,
    get_normalization_service,
)
from app.main import app
from app.schemas.document import DocumentType, ProcessingStage, ProcessingStatus
from app.schemas.extracted_jd import ExtractedJDRead, JDExtractResult
from app.schemas.normalized_jd import (
    CanonicalExperienceRequirement,
    JDNormalizeResult,
    NormalizedJDRead,
    NormalizationMetadata,
)
from app.services.jd_extraction_service import ExtractedJDNotFoundException
from app.services.jd_normalization_service import NormalizedJDNotFoundException


class FakeExtractionService:
    def __init__(self) -> None:
        self.extractions: dict[UUID, ExtractedJDRead] = {}

    async def extract_document(self, document_id: UUID) -> JDExtractResult:
        now = datetime.now(UTC)
        extracted = ExtractedJDRead(
            id=uuid4(),
            document_id=document_id,
            domain="Software Engineering",
            skills=["python", "fastapi"],
            responsibilities=["Design APIs"],
            education=["Bachelor's degree"],
            experience=["3+ years"],
            certifications=[],
            keywords=["python"],
            confidence_scores={"overall": 0.8},
            raw_metadata={},
            created_at=now,
            updated_at=now,
        )
        self.extractions[document_id] = extracted
        return JDExtractResult(
            document_id=document_id,
            document_type=DocumentType.JOB_DESCRIPTION,
            processing_stage=ProcessingStage.EXTRACTION,
            processing_status=ProcessingStatus.COMPLETED,
            message="Extracted successfully",
        )

    async def get_extracted_document(self, document_id: UUID) -> ExtractedJDRead:
        if document_id not in self.extractions:
            raise ExtractedJDNotFoundException()
        return self.extractions[document_id]


class FakeNormalizationService:
    def __init__(self, extraction_service: FakeExtractionService) -> None:
        self.extraction_service = extraction_service
        self.normalizations: dict[UUID, NormalizedJDRead] = {}

    async def normalize_document(self, document_id: UUID) -> JDNormalizeResult:
        extracted = await self.extraction_service.get_extracted_document(document_id)
        now = datetime.now(UTC)
        normalized = NormalizedJDRead(
            id=uuid4(),
            document_id=document_id,
            extracted_job_description_id=extracted.id,
            skills=["python", "fastapi"],
            degree_requirements=["Bachelor's Degree"],
            experience_requirements=[
                CanonicalExperienceRequirement(
                    minimum_months=36, display_value="3+ years"
                )
            ],
            domain="Software Engineering",
            keywords=["python"],
            normalization_metadata=NormalizationMetadata(
                normalized_at=now.isoformat(),
                changes=[],
                warnings=[],
                field_confidence={},
            ),
            ruleset_version="1.0",
            created_at=now,
            updated_at=now,
        )
        self.normalizations[document_id] = normalized
        return JDNormalizeResult(
            document_id=document_id,
            document_type=DocumentType.JOB_DESCRIPTION,
            processing_stage=ProcessingStage.NORMALIZATION,
            processing_status=ProcessingStatus.COMPLETED,
            ruleset_version="1.0",
            message="Normalized successfully",
        )

    async def get_normalized_document(self, document_id: UUID) -> NormalizedJDRead:
        if document_id not in self.normalizations:
            raise NormalizedJDNotFoundException()
        return self.normalizations[document_id]


@pytest.mark.asyncio
async def test_extraction_and_normalization_api_flow(
    async_client: httpx.AsyncClient,
) -> None:
    fake_extract = FakeExtractionService()
    fake_normalize = FakeNormalizationService(fake_extract)

    app.dependency_overrides[get_extraction_service] = lambda: fake_extract
    app.dependency_overrides[get_normalization_service] = lambda: fake_normalize

    doc_id = uuid4()

    # 1. Post extract
    extract_resp = await async_client.post(f"/api/v1/documents/{doc_id}/extract")
    assert extract_resp.status_code == 200
    assert extract_resp.json()["data"]["processing_stage"] == "EXTRACTION"

    # 2. Get extracted
    get_ext_resp = await async_client.get(f"/api/v1/documents/{doc_id}/extracted")
    assert get_ext_resp.status_code == 200
    assert get_ext_resp.json()["data"]["domain"] == "Software Engineering"

    # 3. Post normalize
    normalize_resp = await async_client.post(f"/api/v1/documents/{doc_id}/normalize")
    assert normalize_resp.status_code == 200
    assert normalize_resp.json()["data"]["processing_stage"] == "NORMALIZATION"

    # 4. Get normalized
    get_norm_resp = await async_client.get(f"/api/v1/documents/{doc_id}/normalized")
    assert get_norm_resp.status_code == 200
    assert get_norm_resp.json()["data"]["degree_requirements"] == ["Bachelor's Degree"]

    # 5. Missing document / extraction 404
    missing_resp = await async_client.get(f"/api/v1/documents/{uuid4()}/extracted")
    assert missing_resp.status_code == 404

    app.dependency_overrides.clear()
