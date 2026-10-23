import pytest
from uuid import uuid4
from unittest.mock import AsyncMock

from app.services.jd_extraction_service import (
    JDExtractionService,
    _split_sections,
    _extract_education,
    _extract_experience,
    clean_education_phrase,
    _is_action_sentence,
)
from app.services.jd_normalization_service import (
    JDNormalizationService,
    _canonicalize_degree,
)


CLOUDOPS_JD_FIXTURE = """
Role: Senior CloudOps Engineer
Company: CloudScale Solutions

About the Role:
We are seeking a seasoned CloudOps Engineer to manage, scale, and maintain our multi-cloud infrastructure.

Roles & Responsibilities:
- Will be responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana).
- Deploy and maintain highly available Kubernetes clusters on AWS and Azure.
- Automate CI/CD pipelines using GitHub Actions and Terraform for infrastructure as code.
- Ensure 99.99% system uptime and respond to production incidents.

What You Bring:
- 6–8 years of experience in Cloud Operations or DevOps engineering.
- Deep expertise in AWS, Docker, Kubernetes, Terraform, and Linux administration.
- Proven hands-on experience with Prometheus, Grafana, and Datadog monitoring.
- Strong scripting skills in Python and Bash.

Preferred Skills:
- Experience with Kafka, Redis, and Elasticsearch.
- AWS Certified Solutions Architect or CKA certification.
"""


CLOUDOPS_JD_WITH_EDUCATION = """
Position: Cloud Operations Specialist

What You'll Do:
- Will be responsible for monitoring tools and dashboards across our cloud environments.
- Configure alerting rules in Prometheus and Datadog.

Requirements:
- Bachelor of Technology in Computer Science or related field.
- 5–7 years of relevant experience in cloud systems.
- Strong proficiency in AWS, Docker, and Kubernetes.
"""


PLAIN_TEXT_TRADITIONAL_JD = """
Software Development Engineer II

Job Summary:
Join our core platform engineering team to build scalable microservices.

Responsibilities:
- Design, build, and maintain RESTful APIs using Python and FastAPI.
- Collaborate with frontend engineers to integrate React components.
- Participate in code reviews and architectural discussions.

Qualifications:
- B.E. in Computer Science, Information Technology, or equivalent discipline.
- 3 to 5 years of software engineering experience.
- Strong knowledge of Python, PostgreSQL, Redis, and Git.

Preferred Qualifications:
- Master of Science in Computer Science is a plus.
- Familiarity with Docker and CI/CD pipelines.
"""


def test_cloudops_jd_headings_classification() -> None:
    """Verify alternative section headings are properly classified."""
    sections = _split_sections(CLOUDOPS_JD_FIXTURE)
    assert "responsibilities" in sections
    assert "required_skills" in sections
    assert "preferred_skills" in sections
    # Ensure no false 'education' section was recognized
    assert "education" not in sections


def test_monitoring_responsibility_not_in_education() -> None:
    """
    Root Cause Verification:
    Responsibility line about monitoring tools and dashboards MUST NOT appear under Education.
    Previously, 'Will be' matched '\\bb.?e\\b' (be) as 'Bachelor of Engineering'.
    """
    line = "Will be responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana)."
    assert _is_action_sentence(line) is True

    # Check extraction on line
    extracted_edu, conf = _extract_education(line)
    assert extracted_edu == []
    assert conf == 0.0

    # Check canonicalization does not treat it as a degree
    canonical, rule = _canonicalize_degree(line)
    assert canonical == ""
    assert rule == "degree_map:ignored_action_sentence"


def test_cloudops_jd_education_is_empty_when_not_specified() -> None:
    """
    Task 4: When no education is mentioned in the JD, education must be empty/unspecified.
    Must not invent qualifications from responsibilities or requirements.
    """
    sections = _split_sections(CLOUDOPS_JD_FIXTURE)
    education_source = sections.get("education", "")
    if not education_source:
        candidate_parts = [sections.get("required_skills", ""), sections.get("header", "")]
        education_source = "\n".join(p for p in candidate_parts if p) or CLOUDOPS_JD_FIXTURE

    education, conf = _extract_education(education_source)
    assert education == []
    assert conf == 0.0


def test_cloudops_experience_range_preservation_no_duplicate_subspans() -> None:
    """
    Task 5: Preserve experience ranges such as '6–8 years' without sub-fragment duplicates.
    Previously, '6–8 years of experience' produced both '6–8 years of experience' AND '8 years of experience'.
    """
    experience, conf = _extract_experience(CLOUDOPS_JD_FIXTURE)
    assert conf > 0.0
    # Exactly one experience entry matching 6-8 years, no sub-fragment '8 years'
    range_matches = [exp for exp in experience if "6–8" in exp or "6-8" in exp]
    assert len(range_matches) == 1
    assert not any(exp.strip() == "8 years of experience" for exp in experience)


def test_skills_and_responsibilities_isolation() -> None:
    """
    Task 6: Technical skills extracted across the entire JD while responsibilities
    remain strictly in responsibilities without polluting education or standalone skills.
    """
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    ai_extractor = AsyncMock()
    ai_extractor.extract = AsyncMock(return_value=None)

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo, ai_extractor)

    import asyncio
    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_JD_FIXTURE, uuid4()))

    # Education must be empty
    assert extracted.education == []

    # Responsibilities must contain the monitoring responsibility
    assert any("monitoring tools and dashboards" in resp.lower() for resp in extracted.responsibilities)
    assert not any("monitoring tools" in edu.lower() for edu in extracted.education)

    # Technical skills extracted properly
    skill_names_lower = {s.lower() for s in extracted.skills}
    for expected_skill in ["AWS", "Docker", "Kubernetes", "Terraform", "Prometheus", "Grafana", "Datadog", "Python"]:
        assert expected_skill.lower() in skill_names_lower

    # Experience preserved as range
    assert any("6–8 years" in exp for exp in extracted.experience)
    assert not any(exp == "8 years of experience" for exp in extracted.experience)


def test_backward_compatibility_traditional_jd_with_degrees() -> None:
    """
    Ensure existing plain-text JDs with real degrees (B.E., Master of Science)
    continue to extract and canonicalize correctly.
    """
    sections = _split_sections(PLAIN_TEXT_TRADITIONAL_JD)
    assert "responsibilities" in sections
    assert "required_skills" in sections

    extracted_edu, conf = _extract_education(PLAIN_TEXT_TRADITIONAL_JD)
    assert conf > 0.0
    assert any("B.E. in Computer Science" in edu for edu in extracted_edu)

    # Normalization canonicalization
    canonical_be, rule_be = _canonicalize_degree("B.E. in Computer Science, Information Technology, or equivalent discipline.")
    assert canonical_be == "Bachelor of Engineering in Computer Science, Information Technology"
    assert rule_be == "degree_map:Bachelor of Engineering"

    canonical_ms, rule_ms = _canonicalize_degree("Master of Science in Computer Science is a plus.")
    assert canonical_ms == "Master of Science in Computer Science"
    assert rule_ms == "degree_map:Master of Science"


def test_jd_with_explicit_education_section_and_action_responsibilities() -> None:
    """Verify JD with both explicit education and monitoring responsibilities."""
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    ai_extractor = AsyncMock()
    ai_extractor.extract = AsyncMock(return_value=None)

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo, ai_extractor)

    import asyncio
    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_JD_WITH_EDUCATION, uuid4()))

    # Education should contain only B.Tech, NOT the monitoring line
    assert len(extracted.education) == 1
    assert "Bachelor of Technology in Computer Science" in extracted.education[0]
    assert not any("monitoring tools" in edu.lower() for edu in extracted.education)

    # Responsibilities should contain the monitoring duty
    assert any("monitoring tools and dashboards" in resp.lower() for resp in extracted.responsibilities)

    # Experience range 5-7 years
    assert any("5–7 years" in exp for exp in extracted.experience)
