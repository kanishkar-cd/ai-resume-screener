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

<<<<<<< Updated upstream
    # Verify skills case-preserving deduplication
    assert payload.skills == ["Python", "FastAPI", "ReactJS"]
    # Verify degree mapping
    assert "Bachelor's Degree" in payload.degree_requirements
    assert "Doctor of Philosophy (PhD)" in payload.degree_requirements
=======
    # Verify skills case-preserving deduplication and canonicalization
    assert payload.skills == ["Python", "FastAPI", "React.js"]
    # Verify degree mapping preserving specialization
    assert any("Bachelor's Degree" in d for d in payload.degree_requirements)
    assert any("Doctor of Philosophy (PhD)" in d for d in payload.degree_requirements)
>>>>>>> Stashed changes
    # Verify experience translation to months
    assert any(req.minimum_months == 60 for req in payload.experience_requirements)
    assert any(req.minimum_months == 36 and req.maximum_months == 60 for req in payload.experience_requirements)
    # Check changes tracking
    meta = payload.normalization_metadata
    assert len(meta.changes) > 0
    assert any(c.field == "education" for c in meta.changes)


@pytest.mark.asyncio
async def test_jd_normalization_generic_varied_structures() -> None:
    """Test generic normalization across multiple JD structures preserving OR choices & missing sections."""
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

    # 1. Structure with OR education alternatives, explicit preferred vs mandatory, and responsibilities
    extracted_repo.get_by_document_id.return_value = AsyncMock(
        id=uuid4(),
        job_title="Lead Data Engineer",
        skills=["PySpark", "Snowflake", "dbt", "AWS"],
        required_skills=["PySpark", "Snowflake"],
        preferred_skills=["dbt", "AWS"],
        responsibilities=[
            "Architect end-to-end data pipelines",
            "Optimize Snowflake warehouse queries",
            "Mentor junior data engineers",
        ],
        education=["Bachelor's in Computer Science OR Master's in Data Science OR equivalent experience"],
        education_disciplines=["Computer Science", "Data Science"],
        experience=["7+ years of experience in Data Engineering"],
        certifications=["AWS Certified Data Analytics"],
        keywords=["Lead Data Engineer", "PySpark", "Snowflake"],
        domain="Data Engineering",
        confidence_scores={"skills": 0.95, "education": 0.9, "experience": 0.9, "certifications": 0.85},
    )

    service = JDNormalizationService(doc_repo, extracted_repo, normalized_repo)
    await service.normalize_document(doc_id)

    payload = normalized_repo.upsert.await_args[0][0]
    assert payload.job_title == "Lead Data Engineer"
    assert payload.required_skills == ["PySpark", "Snowflake"]
    assert payload.preferred_skills == ["dbt", "AWS"]
    assert payload.skills == ["PySpark", "Snowflake", "dbt", "AWS"]
    assert len(payload.responsibilities) == 3
    assert "Architect end-to-end data pipelines" in payload.responsibilities
    assert "Bachelor's Degree" in payload.degree_requirements or "Master's Degree" in payload.degree_requirements
    assert payload.certifications == ["AWS Certified Data Analytics"]

    # 2. Minimal JD with missing preferred skills, missing certifications, missing responsibilities
    doc_id_minimal = uuid4()
    doc_repo.get_document.return_value = AsyncMock(
        id=doc_id_minimal,
        document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        processing_status=ProcessingStatusEnum.COMPLETED,
        metadata_json={},
    )
    extracted_repo.get_by_document_id.return_value = AsyncMock(
        id=uuid4(),
        job_title="Junior Developer",
        skills=["Python", "Git"],
        required_skills=["Python", "Git"],
        preferred_skills=[],
        responsibilities=[],
        education=[],
        education_disciplines=[],
        experience=[],
        certifications=[],
        keywords=["Junior Developer", "Python"],
        domain="Software Engineering",
        confidence_scores={"skills": 0.8, "education": 0.0, "experience": 0.0, "certifications": 0.0},
    )

    await service.normalize_document(doc_id_minimal)
    payload_minimal = normalized_repo.upsert.await_args[0][0]
    assert payload_minimal.preferred_skills == []
    assert payload_minimal.responsibilities == []
    assert payload_minimal.degree_requirements == []
    assert payload_minimal.certifications == []

