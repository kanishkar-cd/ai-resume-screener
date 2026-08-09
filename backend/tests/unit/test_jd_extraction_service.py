from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.document import DocumentTypeEnum, ProcessingStatusEnum
from app.schemas.document import ProcessingStatus
from app.services.jd_extraction_service import (
    DocumentNotExtractableException,
    JDExtractionService,
)


@pytest.mark.asyncio
async def test_jd_extraction_wrong_document_type() -> None:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()

    # Document type is RESUME instead of JOB_DESCRIPTION
    doc_repo.get_document.return_value = AsyncMock(
        id=uuid4(),
        document_type=DocumentTypeEnum.RESUME,
        processing_status=ProcessingStatusEnum.PARSED,
        metadata_json={},
    )

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)

    with pytest.raises(DocumentNotExtractableException) as exc:
        await service.extract_document(uuid4())
    assert "JOB_DESCRIPTION documents only" in str(exc.value)


@pytest.mark.asyncio
async def test_jd_extraction_unparsed_document() -> None:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()

    # Document is in UPLOADED state, not parsed yet
    doc_repo.get_document.return_value = AsyncMock(
        id=uuid4(),
        document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        processing_status=ProcessingStatusEnum.UPLOADED,
        metadata_json={},
    )

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)

    with pytest.raises(DocumentNotExtractableException):
        await service.extract_document(uuid4())


@pytest.mark.asyncio
async def test_jd_extraction_successful_patterns() -> None:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()

    doc_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(
        id=doc_id,
        document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        processing_status=ProcessingStatusEnum.PARSED,
        metadata_json={},
    )
    doc_repo.update_status.return_value = AsyncMock(
        processing_status=ProcessingStatusEnum.COMPLETED,
        processing_stage=ProcessingStatus.COMPLETED,
    )

    # Mock raw parsed text content containing explicit signals
    sample_text = """
    We are looking for a Senior DevOps Engineer.
    Requirements:
    - Bachelor's degree in Computer Science
    - AWS Certified Solutions Architect
    - 5+ years of experience in SRE role
    - Strong skills in python, kubernetes, terraform, and postgresql

    Responsibilities:
    - Design and develop scalable cloud architecture
    - Build and maintain CI/CD pipelines
    - Optimize database queries
    """
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text=sample_text,
        word_count=50,
    )

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    result = await service.extract_document(doc_id)

    assert result.document_id == doc_id
    assert result.processing_status == ProcessingStatus.COMPLETED

    extracted_repo.upsert.assert_awaited_once()
    payload = extracted_repo.upsert.await_args[0][0]

    assert "python" in payload.skills
    assert "kubernetes" in payload.skills
    assert "terraform" in payload.skills
    assert "postgresql" in payload.skills
    assert any("Bachelor's degree" in edu for edu in payload.education)
    assert any("5+ years" in exp for exp in payload.experience)
    assert any("aws certified" in cert.lower() for cert in payload.certifications)
    assert len(payload.responsibilities) >= 2
    assert payload.domain == "DevOps / Infrastructure"
