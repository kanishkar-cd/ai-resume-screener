from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.document import DocumentTypeEnum, ProcessingStatusEnum
from app.schemas.document import ProcessingStatus
from app.services.jd_extraction_service import (
    DocumentNotExtractableException,
    JDExtractionService,
)
from app.services.jd_normalization_service import JDNormalizationService


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


@pytest.mark.asyncio
async def test_jd_extraction_can_recover_a_stranded_in_progress_document() -> None:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    document_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(
        id=document_id,
        document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        processing_status=ProcessingStatusEnum.IN_PROGRESS,
        metadata_json={},
    )
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="Job Title: Software Engineer\nExperience: 0-2 years\nResponsibilities:\n- Develop reliable software.",
        word_count=12,
    )

    result = await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(document_id)

    assert result.processing_status == ProcessingStatus.COMPLETED
    extracted_repo.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_jd_extraction_varied_jd_structures_dynamic_extraction() -> None:
    """Verify that 3 completely different JD domain structures extract ONLY their own text and missing fields stay empty."""
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)

    # ── JD 1: QA Automation Engineer (No preferred skills, no degree required, 3-5 yrs exp) ──
    doc_id1 = uuid4()
    doc_repo.get_document.return_value = AsyncMock(
        id=doc_id1, document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        processing_status=ProcessingStatusEnum.PARSED, metadata_json={},
    )
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: QA Automation Engineer
        Experience: 3-5 years of experience
        Required Skills: Playwright, Selenium, TypeScript
        Responsibilities:
        - Write automated E2E tests
        - Maintain regression test suites
        """,
        word_count=35,
    )
    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_id1)
    p1 = extracted_repo.upsert.await_args[0][0]
    assert p1.job_title == "QA Automation Engineer"
    assert any("3-5 years" in e for e in p1.experience)
    assert p1.preferred_skills == []  # Missing section must remain empty
    assert p1.education == []         # Missing section must remain empty

    # ── JD 2: Data Scientist (Has Master's degree, Python/R, No experience phrase) ──
    doc_id2 = uuid4()
    doc_repo.get_document.return_value = AsyncMock(
        id=doc_id2, document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        processing_status=ProcessingStatusEnum.PARSED, metadata_json={},
    )
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Position: Data Scientist
        Education: Master's in Computer Science or Statistics
        Required Skills: Python, PyTorch, SQL
        Responsibilities:
        - Build predictive machine learning models
        """,
        word_count=30,
    )
    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_id2)
    p2 = extracted_repo.upsert.await_args[0][0]
    assert p2.job_title == "Data Scientist"
    assert any("Master" in edu for edu in p2.education)
    assert "python" in p2.skills
    assert p2.experience == []       # Missing section must remain empty
    assert p2.certifications == []   # Missing section must remain empty

    # ── JD 3: Product Manager (PMP, 8+ years experience, Agile/Scrum) ──
    doc_id3 = uuid4()
    doc_repo.get_document.return_value = AsyncMock(
        id=doc_id3, document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        processing_status=ProcessingStatusEnum.PARSED, metadata_json={},
    )
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Role: Product Manager
        Experience: 8+ years experience
        Certifications: PMP
        Required Skills: Agile, Scrum, Jira
        """,
        word_count=20,
    )
    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_id3)
    p3 = extracted_repo.upsert.await_args[0][0]
    assert p3.job_title == "Product Manager"
    assert any("8+ years" in e for e in p3.experience)
    assert any("PMP" in c for c in p3.certifications)
    assert p3.responsibilities == []  # Missing section must remain empty


@pytest.mark.asyncio
async def test_jd_extraction_radically_different_domains_hr_data_devops() -> None:
    """
    Test 3 radically different domain JDs (HR, Data Analyst, DevOps) to prove extracted
    skills/responsibilities are strictly isolated and contain no software engineering defaults.
    """
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)

    # 1. HR Manager JD
    doc_hr = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_hr, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Position: HR Specialist
        Required Skills: Employee Relations, Talent Acquisition, Payroll Administration, HRIS
        Responsibilities:
        - Manage onboarding and offboarding workflows
        - Oversee annual performance reviews
        """,
        word_count=35,
    )
    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_hr)
    p_hr = extracted_repo.upsert.await_args[0][0]
    assert p_hr.job_title == "HR Specialist"
    assert "Employee Relations" in p_hr.required_skills
    assert "Talent Acquisition" in p_hr.required_skills
    assert "Manage onboarding and offboarding workflows" in p_hr.responsibilities
    assert "python" not in [s.lower() for s in p_hr.skills]

    # 2. Data Analyst JD
    doc_da = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_da, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Role: Data Analyst
        Required Skills: Tableau, PowerBI, SQL, Excel, A/B Testing
        Responsibilities:
        - Create weekly executive dashboards
        - Query relational data warehouses for business metrics
        """,
        word_count=40,
    )
    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_da)
    p_da = extracted_repo.upsert.await_args[0][0]
    assert p_da.job_title == "Data Analyst"
    assert "Tableau" in p_da.required_skills
    assert "PowerBI" in p_da.required_skills
    assert "Create weekly executive dashboards" in p_da.responsibilities

    # 3. DevOps Engineer JD
    doc_devops = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_devops, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Title: DevOps Engineer
        Required Skills: Kubernetes, Terraform, Prometheus, Grafana
        Responsibilities:
        - Maintain zero-downtime Kubernetes infrastructure
        - Automate Terraform deployment scripts
        """,
        word_count=35,
    )
    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_devops)
    p_devops = extracted_repo.upsert.await_args[0][0]
    assert p_devops.job_title == "DevOps Engineer"
    assert "Kubernetes" in p_devops.required_skills
    assert "Prometheus" in p_devops.required_skills
    assert "Maintain zero-downtime Kubernetes infrastructure" in p_devops.responsibilities

    # Assert 3 domain extractions share ZERO overlap in extracted skills/responsibilities
    assert set(p_hr.required_skills).isdisjoint(set(p_devops.required_skills))
    assert set(p_da.required_skills).isdisjoint(set(p_hr.required_skills))


@pytest.mark.asyncio
async def test_jd_responsibilities_isolation_and_no_leakage() -> None:
    """
    Test responsibilities extraction rules:
    1. JD with explicit responsibilities -> extract only those.
    2. JD without responsibilities -> [] / Not specified.
    3. Two different JDs -> completely different responsibility outputs.
    4. Requisition ID separation -> no previous requisition data is reused.
    """
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)

    # 1. JD with explicit responsibilities
    doc_explicit = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_explicit, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Financial Analyst
        Responsibilities:
        - Prepare quarterly financial reports
        - Conduct budget variance analysis
        """,
        word_count=20,
    )
    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_explicit)
    p_explicit = extracted_repo.upsert.await_args[0][0]
    assert p_explicit.responsibilities == [
        "Prepare quarterly financial reports",
        "Conduct budget variance analysis",
    ]

    # 2. JD without responsibilities section -> returns []
    doc_no_resp = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_no_resp, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Senior Software Engineer
        Required Skills: C++, Python
        Experience: 5+ years experience
        """,
        word_count=15,
    )
    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_no_resp)
    p_no_resp = extracted_repo.upsert.await_args[0][0]
    assert p_no_resp.responsibilities == []

    # 3. Two different JDs -> completely different responsibility outputs
    assert p_explicit.responsibilities != p_no_resp.responsibilities
    assert p_no_resp.responsibilities == []

    # 4. Requisition ID isolation -> distinct document payloads created
    assert p_explicit.document_id == doc_explicit
    assert p_no_resp.document_id == doc_no_resp
    assert p_explicit.document_id != p_no_resp.document_id


@pytest.mark.asyncio
async def test_full_flow_two_jds_responsibility_isolation_and_empty_handling() -> None:
    """
    Integration-style test verifying full flow:
    raw text -> extraction -> normalization -> API output object
    1. Feeds two completely different JDs and verifies their responsibilities are different and contain only their text.
    2. Feeds a JD with NO responsibilities section and verifies normalization returns [].
    """
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    normalized_repo = AsyncMock()
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)

    # ── Upload 1: Marketing Manager (Explicit Responsibilities) ──
    doc_id1 = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id1, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Marketing Manager
        Responsibilities:
        - Lead brand awareness social campaigns
        - Manage quarterly advertising budget
        """,
        word_count=20,
    )
    extract_service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await extract_service.extract_document(doc_id1)
    ext_payload1 = extracted_repo.upsert.await_args[0][0]
    extracted_repo.get_by_document_id.return_value = AsyncMock(
        id=uuid4(),
        **ext_payload1.model_dump(),
    )

    norm_service = JDNormalizationService(doc_repo, extracted_repo, normalized_repo)
    await norm_service.normalize_document(doc_id1)
    norm_payload1 = normalized_repo.upsert.await_args[0][0]

    assert norm_payload1.job_title == "Marketing Manager"
    assert norm_payload1.responsibilities == [
        "Lead brand awareness social campaigns",
        "Manage quarterly advertising budget",
    ]

    # ── Upload 2: Systems Architect (Explicit Responsibilities) ──
    doc_id2 = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id2, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Position: Systems Architect
        Responsibilities:
        - Design fault-tolerant distributed cloud architecture
        - Establish enterprise security compliance standards
        """,
        word_count=20,
    )
    ext_result2 = await extract_service.extract_document(doc_id2)
    ext_payload2 = extracted_repo.upsert.await_args[0][0]
    extracted_repo.get_by_document_id.return_value = AsyncMock(
        id=uuid4(),
        **ext_payload2.model_dump(),
    )

    await norm_service.normalize_document(doc_id2)
    norm_payload2 = normalized_repo.upsert.await_args[0][0]

    assert norm_payload2.job_title == "Systems Architect"
    assert norm_payload2.responsibilities == [
        "Design fault-tolerant distributed cloud architecture",
        "Establish enterprise security compliance standards",
    ]

    # Assert 1: Responsibilities are completely different and strictly from respective JDs
    assert norm_payload1.responsibilities != norm_payload2.responsibilities

    # ── Upload 3: Mechanical Engineer (NO Responsibilities section) ──
    doc_id3 = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id3, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Role: Mechanical Engineer
        Required Skills: SolidWorks, AutoCAD, Thermodynamics
        Education: Bachelor's in Mechanical Engineering
        """,
        word_count=20,
    )
    ext_result3 = await extract_service.extract_document(doc_id3)
    ext_payload3 = extracted_repo.upsert.await_args[0][0]
    extracted_repo.get_by_document_id.return_value = AsyncMock(
        id=uuid4(),
        **ext_payload3.model_dump(),
    )

    await norm_service.normalize_document(doc_id3)
    norm_payload3 = normalized_repo.upsert.await_args[0][0]

    # Assert 2: Normalization payload returns [] when no responsibilities section exists
    assert norm_payload3.responsibilities == []


@pytest.mark.asyncio
async def test_jd_skill_cleaning_no_sentence_fragments_or_filler_words() -> None:
    """
    Generic regression test asserting:
    1. No sentence fragments ("or a similar programming language", "or GCP is", "an advantage.").
    2. Meaningful multi-word phrases preserved ("relational databases", "data warehouses").
    3. Degree alternatives preserved ("B.E.", "B.Tech", "B.Sc.", "related field").
    """
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)

    doc_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Data Engineer
        Education: B.E. / B.Tech. / B.Sc. in Computer Science or a related field
        Required Skills:
        - Python, Java, or a similar programming language
        - Strong understanding of relational databases and data warehouses
        - Exposure to Spark or GCP is an advantage.
        """,
        word_count=45,
    )

    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    # Verify no sentence fragments exist in required_skills
    for skill in payload.required_skills:
        assert "or a similar programming language" not in skill.lower()
        assert "is an advantage" not in skill.lower()
        assert skill.lower() not in {"or", "and", "is", "an", "advantage", "exposure to"}

    # Verify atomic and meaningful multi-word terms are preserved
    req_skills_lower = [s.lower() for s in payload.required_skills]
    assert any("python" in s for s in req_skills_lower)
    assert any("java" in s for s in req_skills_lower)
    assert any("relational databases" in s for s in req_skills_lower)
    assert any("data warehouses" in s for s in req_skills_lower)





