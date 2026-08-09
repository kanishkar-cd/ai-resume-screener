from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.document import DocumentTypeEnum, ProcessingStatusEnum
from app.schemas.document import ProcessingStatus
from app.services.jd_normalization_service import (
    DocumentNotNormalizableException,
    JDNormalizationService,
    _parse_experience_phrase,
)


def test_experience_phrase_parsing() -> None:
    # Test range
    req_range = _parse_experience_phrase("3-5 years of experience")
    assert req_range.minimum_months == 36
    assert req_range.maximum_months == 60

    # Test plus
    req_plus = _parse_experience_phrase("8+ years experience")
    assert req_plus.minimum_months == 96
    assert req_plus.maximum_months is None

    # Test minimum plain
    req_min = _parse_experience_phrase("minimum of 2 years")
    assert req_min.minimum_months == 24
    assert req_min.maximum_months is None


@pytest.mark.asyncio
async def test_jd_normalization_missing_extracted_raises_error() -> None:
    doc_repo = AsyncMock()
    extracted_repo = AsyncMock()
    normalized_repo = AsyncMock()

    doc_repo.get_document.return_value = AsyncMock(id=uuid4())
    extracted_repo.get_by_document_id.return_value = None

    service = JDNormalizationService(doc_repo, extracted_repo, normalized_repo)

    with pytest.raises(Exception):
        await service.normalize_document(uuid4())


@pytest.mark.asyncio
async def test_jd_normalization_successful_canonicalization() -> None:
    doc_repo = AsyncMock()
    extracted_repo = AsyncMock()
    normalized_repo = AsyncMock()

    doc_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(
        id=doc_id,
        document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        processing_status=ProcessingStatusEnum.COMPLETED,
        metadata_json={},
    )
    doc_repo.update_status.return_value = AsyncMock(
        processing_status=ProcessingStatusEnum.COMPLETED,
    )

    # Mock extracted entity with dirty values
    extracted_repo.get_by_document_id.return_value = AsyncMock(
        id=uuid4(),
        skills=["Python", "FastAPI", "ReactJS"],
        education=["Bachelor's degree in CS", "PHD in Math"],
        experience=["5+ years experience", "3 to 5 years"],
        keywords=["DevOps", "Python"],
        domain="Software Engineering",
        confidence_scores={"skills": 0.9, "education": 0.8, "experience": 0.7, "certifications": 0.0},
    )

    service = JDNormalizationService(doc_repo, extracted_repo, normalized_repo)
    result = await service.normalize_document(doc_id)

    assert result.document_id == doc_id
    assert result.processing_status == ProcessingStatus.COMPLETED

    normalized_repo.upsert.assert_awaited_once()
    payload = normalized_repo.upsert.await_args[0][0]

    # Verify skills are lowercased and sorted
    assert payload.skills == ["fastapi", "python", "reactjs"]
    # Verify degree mapping
    assert "Bachelor's Degree" in payload.degree_requirements
    assert "Doctor of Philosophy (PhD)" in payload.degree_requirements
    # Verify experience translation to months
    assert any(req.minimum_months == 60 for req in payload.experience_requirements)
    assert any(req.minimum_months == 36 and req.maximum_months == 60 for req in payload.experience_requirements)
    # Check changes tracking
    meta = payload.normalization_metadata
    assert len(meta.changes) > 0
    assert any(c.field == "education" for c in meta.changes)
