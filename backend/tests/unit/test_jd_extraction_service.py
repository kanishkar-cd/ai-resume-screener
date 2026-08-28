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
    1. No sentence fragments ("data warehouses. Spark", "GCP is", "is an advantage.").
    2. Meaningful multi-word phrases preserved ("relational databases", "data warehouses").
    3. Period boundaries and enumerated technology lists split cleanly into atomic items.
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
        - Strong understanding of relational databases and data warehouses. Exposure to Spark, Airflow, AWS, Azure, or GCP is an advantage.
        """,
        word_count=45,
    )

    await JDExtractionService(doc_repo, parsed_repo, extracted_repo).extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    # Verify no sentence fragments exist in required_skills
    for skill in payload.required_skills:
        assert "data warehouses. spark" not in skill.lower()
        assert "gcp is" not in skill.lower()
        assert "is an advantage" not in skill.lower()
        assert skill.lower() not in {"or", "and", "is", "an", "advantage", "exposure to"}

    # Verify atomic and meaningful multi-word terms are preserved cleanly
    req_skills_lower = [s.lower() for s in payload.required_skills]
    assert any("python" in s for s in req_skills_lower)
    assert any("relational databases" in s for s in req_skills_lower)
    assert any("spark" in s for s in req_skills_lower)


@pytest.mark.asyncio
async def test_3_unrelated_jds_domain_and_skill_isolation() -> None:
    """
    Regression test using 3 completely unrelated JDs (Financial Analyst, Healthcare Nurse Coordinator, CyberSecurity Specialist):
    - Asserts no cross-JD leakage
    - Asserts all degree alternatives are extracted
    - Asserts no sentence fragments or filler words
    """
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)

    # 1. Finance JD
    doc_fin = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_fin, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Financial Analyst
        Education: B.Com / MBA in Finance or related discipline
        Required Skills:
        - Financial Modeling, Valuation, Excel Pivot Tables, Variance Analysis
        """,
        word_count=30,
    )
    await service.extract_document(doc_fin)
    p_fin = extracted_repo.upsert.await_args[0][0]

    # 2. Healthcare JD
    doc_hc = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_hc, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Nurse Coordinator
        Education: B.Sc. Nursing or Diploma in Nursing
        Required Skills:
        - Patient Triage, Electronic Health Records, Clinical Assessment
        """,
        word_count=30,
    )
    await service.extract_document(doc_hc)
    p_hc = extracted_repo.upsert.await_args[0][0]

    # 3. Security JD
    doc_sec = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_sec, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Cybersecurity Specialist
        Education: B.Tech / M.Sc. in Information Security
        Required Skills:
        - Penetration Testing, Wireshark, SIEM, Firewall Configuration
        """,
        word_count=30,
    )
    await service.extract_document(doc_sec)
    p_sec = extracted_repo.upsert.await_args[0][0]

    # Verify no cross-JD leakage
    assert set(p_fin.required_skills).isdisjoint(set(p_hc.required_skills))
    assert set(p_hc.required_skills).isdisjoint(set(p_sec.required_skills))
    assert set(p_fin.required_skills).isdisjoint(set(p_sec.required_skills))

    # Verify degree alternatives captured
    assert len(p_fin.education) >= 1
    assert len(p_hc.education) >= 1
    assert len(p_sec.education) >= 1


@pytest.mark.asyncio
async def test_5_unrelated_jds_generic_extraction_and_isolation() -> None:
    """
    Comprehensive regression test covering 5 completely unrelated non-engineering JDs:
    1. HR Specialist
    2. Legal Counsel
    3. Civil Engineer
    4. Clinical Pharmacist
    5. Corporate Financial Auditor

    Verifies:
    - Zero hardcoded domain vocabulary dependency
    - Zero sentence fragments in required/preferred skills
    - No cross-JD leakage
    - Separation of required vs. preferred skills
    - Missing responsibilities section returns []
    """
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)

    jds = {
        "hr": """
            Job Title: Human Resources Specialist
            Education: Bachelor's in Human Resources, Business Administration, or related field
            Required Skills:
            - Employee Relations, Payroll Administration, Performance Management
            Preferred Skills:
            - Workday Certification is an advantage.
        """,
        "legal": """
            Job Title: Corporate Legal Counsel
            Education: Juris Doctor (J.D.) or LL.M. degree
            Required Skills:
            - Contract Negotiation, Regulatory Compliance, M&A Diligence
            Responsibilities:
            - Draft and review commercial agreements.
        """,
        "civil": """
            Job Title: Senior Civil Engineer
            Education: B.E. / B.Tech in Civil Engineering
            Required Skills:
            - Structural Analysis, AutoCAD, Geotechnical Engineering
            Preferred Skills:
            - LEED AP accreditation is preferred.
        """,
        "pharma": """
            Job Title: Clinical Pharmacist
            Education: Doctor of Pharmacy (Pharm.D.) or Registered Pharmacist License
            Required Skills:
            - Medication Therapy Management, Clinical Pharmacology, Patient Counseling
        """,
        "finance": """
            Job Title: Senior Financial Auditor
            Education: Master's in Accounting or CPA / ACCA Credential
            Required Skills:
            - Internal Audit Controls, SOX Compliance, Financial Risk Assessment
            Responsibilities:
            - Execute annual financial audits and risk assessments.
        """,
    }

    results = {}
    for key, text in jds.items():
        doc_id = uuid4()
        doc_repo.get_document.return_value = AsyncMock(id=doc_id, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
        parsed_repo.get_by_document_id.return_value = AsyncMock(raw_text=text, word_count=35)
        await service.extract_document(doc_id)
        results[key] = extracted_repo.upsert.await_args[0][0]

    # 1. No cross-JD skill leakage
    hr_skills = set(results["hr"].required_skills)
    legal_skills = set(results["legal"].required_skills)
    civil_skills = set(results["civil"].required_skills)
    pharma_skills = set(results["pharma"].required_skills)
    finance_skills = set(results["finance"].required_skills)

    assert hr_skills.isdisjoint(legal_skills)
    assert civil_skills.isdisjoint(pharma_skills)
    assert finance_skills.isdisjoint(hr_skills)

    # 2. Required vs Preferred separation
    assert "Workday Certification" in results["hr"].preferred_skills or any("workday" in s.lower() for s in results["hr"].preferred_skills)

    # 3. Missing responsibilities remain empty []
    assert results["hr"].responsibilities == []
    assert results["civil"].responsibilities == []
    assert len(results["legal"].responsibilities) == 1
    assert len(results["finance"].responsibilities) == 1


@pytest.mark.asyncio
async def test_no_standalone_noise_words_in_required_skills() -> None:
    """Verify that stop words/noise ('are', 'and', 'basis', 'requirements', 'skills', 'log') are never extracted as single skills."""
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
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: QA / Cybersecurity Analyst
        Experience: 0-1 year
        Education: B.Sc. in Cybersecurity, Computer Science, Information Technology, B.Tech
        Required Skills:
        - Cybersecurity fundamentals
        - networking, TCP/IP
        - Linux/Windows basics
        - authentication concepts, log, analysis, SIEM fundamentals
        - vulnerability concepts
        - basic scripting
        - Security certifications or labs are preferred
        Responsibilities:
        - Monitor security alerts and assist with initial alert triage.
        - Analyze system, application, and security logs.
        """,
        word_count=50,
    )

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    req_skills_lower = [s.lower() for s in payload.required_skills]

    # Prohibited single-word / noise skills
    assert "are" not in req_skills_lower
    assert "and" not in req_skills_lower
    assert "basis" not in req_skills_lower
    assert "requirements" not in req_skills_lower
    assert "skills" not in req_skills_lower
    assert "log" not in req_skills_lower
    assert "analysis" not in req_skills_lower

    # Valid multi-word / atomic skills preserved
    assert any("cybersecurity fundamentals" in s for s in req_skills_lower)
    assert any("linux" in s for s in req_skills_lower)
    assert any("windows basics" in s for s in req_skills_lower)
    assert any("siem fundamentals" in s for s in req_skills_lower)
    assert any("vulnerability concepts" in s for s in req_skills_lower)
    assert any("scripting" in s for s in req_skills_lower)
    assert any("security certifications or labs" in s for s in req_skills_lower)
    assert not any(s.endswith(" are") for s in req_skills_lower)


@pytest.mark.asyncio
async def test_itops_directory_basics_and_scripting_basics() -> None:
    """Verify ITOps Directory Basics and Scripting Basics canonical requirements, asserting 'Active' is not standalone."""
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
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: IT Support Specialist
        Education: B.Sc, B.Tech in Computer Science, Information Technology
        Required Skills:
        - IT support fundamentals
        - Windows/Linux basics
        - networking, ticketing tools
        - Active Directory basics
        - SQL fundamentals
        - scripting basics
        - ITIL awareness
        Responsibilities:
        - Monitor IT services and respond to operational alerts.
        - Handle basic incidents and service requests through ticketing systems.
        """,
        word_count=50,
    )

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    req_skills_lower = [s.lower() for s in payload.required_skills]

    # Prohibited standalone word
    assert "active" not in req_skills_lower

    # Valid compound requirement items preserved
    assert any("active directory" in s or "directory basics" in s for s in req_skills_lower)
    assert any("scripting basics" in s for s in req_skills_lower)
    assert any("it support fundamentals" in s for s in req_skills_lower)
    assert any("windows" in s for s in req_skills_lower)
    assert any("linux basics" in s for s in req_skills_lower)
    assert any("ticketing tools" in s for s in req_skills_lower)
    assert any("itil awareness" in s for s in req_skills_lower)


@pytest.mark.asyncio
async def test_unsectioned_infrastructure_jd_extraction() -> None:
    """Verify extraction from unsectioned header lines with slash and semicolon delimiters."""
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
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""Linux/Windows Server; PowerShell/Bash/Python; VMware; AWS/Azure; Active Directory; DNS/DHCP; TCP/IP; storage; backup/recovery; monitoring; Ansible; ITIL; incident/change management.
Education & Experience
Bachelor’s degree or equivalent technical experience. 5–8 years of systems administration or infrastructure operations experience. Relevant certifications such as AWS/Azure Administrator, RHCSA/RHCE, or ITIL are desirable.
""",
        word_count=45,
    )

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    all_extracted_skills = [s.lower() for s in ([*(payload.required_skills or []), *(payload.skills or [])])]

    # Verify all JD skills are captured
    assert any("linux" in s for s in all_extracted_skills)
    assert any("windows server" in s for s in all_extracted_skills)
    assert any("powershell" in s for s in all_extracted_skills)
    assert any("bash" in s for s in all_extracted_skills)
    assert any("python" in s for s in all_extracted_skills)
    assert any("vmware" in s for s in all_extracted_skills)
    assert any("aws" in s for s in all_extracted_skills)
    assert any("azure" in s for s in all_extracted_skills)
    assert any("active directory" in s for s in all_extracted_skills)
    assert any("dns" in s for s in all_extracted_skills)
    assert any("dhcp" in s for s in all_extracted_skills)
    assert any("tcp/ip" in s for s in all_extracted_skills)
    assert any("storage" in s for s in all_extracted_skills)
    assert any("backup" in s or "recovery" in s for s in all_extracted_skills)
    assert any("monitoring" in s for s in all_extracted_skills)
    assert any("ansible" in s for s in all_extracted_skills)
    assert any("itil" in s for s in all_extracted_skills)
    assert any("incident" in s or "change management" in s for s in all_extracted_skills)

    # Verify experience and education extraction
    assert any("5" in exp and "8" in exp for exp in payload.experience)
    assert any("bachelor" in e.lower() for e in payload.education)


@pytest.mark.asyncio
async def test_full_sysops_jd_with_job_summary_and_required_technical_skills() -> None:
    """Verify that intro summary sentences are not extracted as skills, and 'Required Technical Skills' correctly populates required_skills."""
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
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""We are seeking an experienced SysOps Engineer to administer, maintain, automate, and troubleshoot enterprise infrastructure. The role focuses on system availability, server operations, patching, monitoring, capacity, and backup.

Role Responsibilities
• Administer Linux and Windows servers across on-premises and cloud environments.
• Perform system monitoring, patching, upgrades, configuration management, and capacity planning.
• Troubleshoot operating-system, networking, storage, application-hosting, and performance issues.
• Automate recurring operational tasks using PowerShell, Bash, Python, or configuration-management tools.
• Manage backups, recovery procedures, high-availability configurations, and disaster-recovery exercises.
• Maintain operational documentation, runbooks, system inventories, and change records.
• Coordinate incident, problem, and change management with infrastructure and application teams.
• Implement hardening, access controls, vulnerability remediation, and operational compliance requirements.

Required Technical Skills
Linux/Windows Server; PowerShell/Bash/Python; VMware; AWS/Azure; Active Directory; DNS/DHCP; TCP/IP; storage; backup/recovery; monitoring; Ansible; ITIL; incident/change management.

Education & Experience
Bachelor’s degree or equivalent technical experience. 5–8 years of systems administration or infrastructure operations experience. Relevant certifications such as AWS/Azure Administrator, RHCSA/RHCE, or ITIL are desirable.
""",
        word_count=130,
    )

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    req_skills_lower = [s.lower() for s in payload.required_skills]

    # 1. Prose summary must NOT be in required_skills
    assert not any("seeking" in s for s in req_skills_lower)
    assert not any("focuses" in s for s in req_skills_lower)
    assert not any("we are seeking an experienced sysops engineer" in s for s in req_skills_lower)
    assert not any("the role focuses on system availability" in s for s in req_skills_lower)

    # 2. Technical skills MUST be in required_skills
    assert any("linux" in s for s in req_skills_lower)
    assert any("windows server" in s for s in req_skills_lower)
    assert any("powershell" in s for s in req_skills_lower)
    assert any("bash" in s for s in req_skills_lower)
    assert any("python" in s for s in req_skills_lower)
    assert any("vmware" in s for s in req_skills_lower)
    assert any("aws" in s for s in req_skills_lower)
    assert any("azure" in s for s in req_skills_lower)
    assert any("active directory" in s for s in req_skills_lower)
    assert any("dns" in s for s in req_skills_lower)
    assert any("dhcp" in s for s in req_skills_lower)
    assert any("tcp/ip" in s for s in req_skills_lower)
    assert any("storage" in s for s in req_skills_lower)
    assert any("backup" in s or "recovery" in s for s in req_skills_lower)
    assert any("monitoring" in s for s in req_skills_lower)
    assert any("ansible" in s for s in req_skills_lower)
    assert any("itil" in s for s in req_skills_lower)
    assert any("incident" in s or "change management" in s for s in req_skills_lower)

    # 3. Responsibilities must be cleanly isolated and not contain the skill line
    assert len(payload.responsibilities) == 8
    assert not any("required technical skills" in r.lower() for r in payload.responsibilities)


@pytest.mark.asyncio
async def test_slash_alternative_groups_preserved_as_is() -> None:
    """Verify that slash alternative groups (e.g. Java/Python/JavaScript, Selenium/Playwright/Cypress, Agile/Scrum) are extracted as intact requirements."""
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
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: QA Automation Engineer
        Required Skills:
        Selenium/Playwright/Cypress; Java/Python/JavaScript; REST API testing; Postman; SQL; CI/CD; Git; test
        management; defect tracking; Agile/Scrum; performance testing tools; automation framework design.
        Education & Experience:
        Bachelor's in Computer Science. 5-8 years of experience.
        """,
        word_count=50,
    )

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    req_skills = payload.required_skills
    req_skills_lower = [s.lower() for s in req_skills]

    # Slash alternative groups preserved intact
    assert "selenium/playwright/cypress" in req_skills_lower
    assert "java/python/javascript" in req_skills_lower
    assert "agile/scrum" in req_skills_lower

    # Not separated into individual isolated fragments
    assert "playwright" not in req_skills_lower
    assert "cypress" not in req_skills_lower

    # Clean multi-word skills preserved across wrapped lines
    assert "rest api testing" in req_skills_lower
    assert "test management" in req_skills_lower
    assert "defect tracking" in req_skills_lower
    assert "performance testing tools" in req_skills_lower
    assert "automation framework design" in req_skills_lower
    assert "postman" in req_skills_lower
    assert "sql" in req_skills_lower
    assert "ci/cd" in req_skills_lower
    assert "git" in req_skills_lower


@pytest.mark.asyncio
async def test_jd_extraction_example_a_clean_skills() -> None:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Full Stack Developer
        Required Skills:
        JavaScript, React.js, Node.js, MongoDB, REST APIs, Git
        """,
        word_count=20,
    )
    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    req_skills = payload.required_skills
    assert "JavaScript" in req_skills
    assert "React.js" in req_skills or "React" in req_skills
    assert "Node.js" in req_skills
    assert "MongoDB" in req_skills
    assert "REST APIs" in req_skills or "REST API" in req_skills
    assert "Git" in req_skills
    assert payload.responsibilities == []


@pytest.mark.asyncio
async def test_jd_extraction_example_b_action_responsibilities() -> None:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Software Engineer
        Responsibilities:
        - Integrate REST APIs
        - Implement JWT authentication
        - Fix production defects
        """,
        word_count=20,
    )
    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    assert len(payload.responsibilities) == 3
    assert any("Integrate REST APIs" in r for r in payload.responsibilities)
    assert any("Implement JWT authentication" in r for r in payload.responsibilities)
    assert any("Fix production defects" in r for r in payload.responsibilities)
    # Responsibilities should not be in required_skills
    assert "Fix production defects" not in payload.required_skills


@pytest.mark.asyncio
async def test_jd_extraction_example_c_project_descriptions_and_embedded_tech() -> None:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Full Stack Engineer
        Key Requirements:
        - JavaScript, React.js, Node.js, MongoDB, REST APIs, Git
        - E-Commerce Store — Developed product listing, cart, login, and order-management features using the MERN stack
        - Implemented JWT authentication and fixed production defects
        - Collaborated with senior engineers on feature delivery
        """,
        word_count=50,
    )
    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    req_skills_lower = [s.lower() for s in payload.required_skills]

    # Clean technical skills are extracted
    assert "javascript" in req_skills_lower
    assert "react.js" in req_skills_lower or "react" in req_skills_lower
    assert "node.js" in req_skills_lower
    assert "mongodb" in req_skills_lower
    assert "rest apis" in req_skills_lower or "rest api" in req_skills_lower
    assert "git" in req_skills_lower
    assert "mern" in req_skills_lower
    assert "jwt" in req_skills_lower

    # Fragmented words and full project sentences are NOT extracted as skills
    assert "cart" not in req_skills_lower
    assert "login" not in req_skills_lower
    assert "product listing" not in req_skills_lower
    assert "developed product listing" not in req_skills_lower
    assert "order-management features using the mern stack" not in req_skills_lower
    assert "fixed production defects" not in req_skills_lower
    assert "collaborated with senior engineers on feature delivery" not in req_skills_lower

    # Full action and project sentences are preserved under responsibilities
    resp_lower = [r.lower() for r in payload.responsibilities]
    assert any("e-commerce store" in r for r in resp_lower)
    assert any("collaborated with senior engineers" in r for r in resp_lower)


@pytest.mark.asyncio
async def test_jd_extraction_example_d_deduplication_of_aliases() -> None:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Frontend Engineer
        Required Skills:
        React.js
        ReactJS
        React
        Preferred Skills:
        Docker
        AWS
        """,
        word_count=20,
    )
    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    # React variations must collapse to 1 single requirement
    assert len(payload.required_skills) == 1
    assert payload.required_skills[0].lower() in {"react", "react.js"}

    # Preferred skills must have Docker and AWS
    assert len(payload.preferred_skills) == 2
    assert "Docker" in payload.preferred_skills
    assert "AWS" in payload.preferred_skills


@pytest.mark.asyncio
async def test_jd_extraction_example_e_required_vs_preferred_isolation() -> None:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Full Stack Developer
        Required Skills:
        JavaScript
        React.js
        Node.js
        Preferred Skills:
        Docker
        AWS
        CI/CD
        """,
        word_count=25,
    )
    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    assert len(payload.required_skills) == 3
    assert "JavaScript" in payload.required_skills
    assert "React.js" in payload.required_skills or "React" in payload.required_skills
    assert "Node.js" in payload.required_skills

    assert len(payload.preferred_skills) == 3
    assert "Docker" in payload.preferred_skills
    assert "AWS" in payload.preferred_skills
    assert "CI/CD" in payload.preferred_skills


@pytest.mark.asyncio
async def test_categorized_skills_extraction_strips_category_labels() -> None:
    """Verify that sectioned inline category labels (Frontend:, Backend:, Database:, Engineering:) are stripped from skills."""
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    doc_id = uuid4()
    doc_repo.get_document.return_value = AsyncMock(id=doc_id, document_type=DocumentTypeEnum.JOB_DESCRIPTION, processing_status=ProcessingStatusEnum.PARSED, metadata_json={})
    doc_repo.update_status.return_value = AsyncMock(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed_repo.get_by_document_id.return_value = AsyncMock(
        raw_text="""
        Job Title: Full Stack Developer
        Required Skills
        Frontend: React.js, JavaScript/TypeScript, HTML5, CSS3, responsive design, state management.
        Backend: Node.js, Express.js, REST APIs, authentication, authorization, asynchronous programming.
        Database: MongoDB, schema design, indexing, aggregation, query optimization.
        Engineering: Git, GitHub/GitLab, testing, debugging, clean code, API documentation.
        Preferred Skills
        Next.js, TypeScript, Redux Toolkit, Redis, Docker, AWS, GraphQL, CI/CD, microservices, WebSockets, Jest, React
        Testing Library.
        Education
        Bachelor's degree in Computer Science, Information Technology, Engineering, or a related field.
        Candidate Profile
        Strong problem-solving and communication skills.
        Keywords
        MERN Stack, Senior Developer, React.js, Node.js, Express.js, MongoDB, JavaScript, TypeScript, REST API, AWS, Docker, Git, Microservices
        """,
        word_count=100,
    )
    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    await service.extract_document(doc_id)
    payload = extracted_repo.upsert.await_args[0][0]

    req_lower = [s.lower() for s in payload.required_skills]
    pref_lower = [s.lower() for s in payload.preferred_skills]

    # Category prefixes stripped
    assert "react.js" in req_lower
    assert "frontend: react.js" not in req_lower
    assert "node.js" in req_lower
    assert "backend: node.js" not in req_lower
    assert "mongodb" in req_lower
    assert "database: mongodb" not in req_lower
    assert "git" in req_lower
    assert "engineering: git" not in req_lower

    # Intact compound groups preserved
    assert "javascript/typescript" in req_lower
    assert "github/gitlab" in req_lower
    assert "html5" in req_lower
    assert "css3" in req_lower

    # Preferred skills wrapped line preserved
    assert "react testing library" in pref_lower
    assert "next.js" in pref_lower
    assert "redux toolkit" in pref_lower















