from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.document import DocumentTypeEnum, ProcessingStatusEnum
from app.schemas.document import ProcessingStatus
from app.services.jd_extraction_service import JDExtractionService
from app.services.jd_normalization_service import JDNormalizationService


SOFTWARE_ENGINEER_JD = """
JOB DESCRIPTION
Job Title: Software Engineer

EXPERIENCE
Experience: 0–2 years
0–2 years of professional or internship experience in software development.

REQUIRED SKILLS
- JavaScript, Python, C++, SQL, HTML and CSS
- REST APIs and Git
- Object-Oriented Programming
- Data Structures and Algorithms
- Software development and debugging

PREFERRED SKILLS
- React.js, Node.js, Express.js, MongoDB and PostgreSQL
- AWS, Docker, CI/CD, Jenkins and GitHub Actions
- IoT, Embedded Systems, PLC Programming, Machine Learning and Linux

EDUCATION
Bachelor's degree in Computer Science, Information Technology, Electronics,
Electronics & Instrumentation, Artificial Intelligence & Data Science,
or a related engineering discipline.

KEY RESPONSIBILITIES
- Develop and maintain software applications and RESTful APIs.
- Design responsive web interfaces using modern web technologies.
- Write clean, maintainable, and reusable code.
- Work with SQL and NoSQL databases.
- Collaborate with engineering teams to deliver reliable products.
- Use Git-based version control and code review workflows.
- Develop and integrate cloud-based applications on AWS.
- Work with containerization and CI/CD pipelines.
- Contribute to IoT, embedded-system, automation, or data-driven projects.
- Troubleshoot software issues and improve application performance.

KEYWORDS
Software Engineer, JavaScript, Python, C++, SQL, HTML, CSS, REST API, Git,
React, Node.js, Express, MongoDB, PostgreSQL, AWS, Docker, CI/CD, Jenkins,
IoT, Embedded Systems, PLC Programming, Machine Learning, Linux
"""


def repositories(text: str = SOFTWARE_ENGINEER_JD):
    document_id = uuid4()
    documents = AsyncMock()
    documents.get_document.return_value = SimpleNamespace(
        id=document_id, document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        processing_status=ProcessingStatusEnum.PARSED, metadata_json={},
    )
    documents.update_status.return_value = SimpleNamespace(processing_status=ProcessingStatusEnum.COMPLETED)
    parsed = AsyncMock()
    parsed.get_by_document_id.return_value = SimpleNamespace(raw_text=text, word_count=len(text.split()))
    extracted = AsyncMock()
    return document_id, documents, parsed, extracted


@pytest.mark.asyncio
async def test_software_engineer_jd_preserves_structured_requirements_through_normalization() -> None:
    document_id, documents, parsed, extracted_repository = repositories()
    await JDExtractionService(documents, parsed, extracted_repository).extract_document(document_id)
    extracted = extracted_repository.upsert.await_args.args[0]

    assert extracted.job_title == "Software Engineer"
    assert extracted.domain == "Software Engineering"
    assert extracted.required_skills == [
        "JavaScript", "Python", "C++", "SQL", "HTML", "CSS", "REST APIs", "Git",
        "Object-Oriented Programming", "Data Structures and Algorithms", "Software development and debugging",
    ]
    assert extracted.preferred_skills == [
        "React.js", "Node.js", "Express.js", "MongoDB", "PostgreSQL", "AWS", "Docker",
        "CI/CD", "Jenkins", "GitHub Actions", "IoT", "Embedded Systems", "PLC Programming",
        "Machine Learning", "Linux",
    ]
    assert any("0–2 years" in value for value in extracted.experience)
    assert any("Bachelor's degree" in value for value in extracted.education)
    assert extracted.education_disciplines == [
        "Computer Science", "Information Technology", "Electronics & Instrumentation",
        "Artificial Intelligence & Data Science", "Electronics", "Related Engineering",
    ]
    assert len(extracted.responsibilities) == 10
    assert all(len(keyword.splitlines()) == 1 for keyword in extracted.keywords)

    extracted_model = SimpleNamespace(id=uuid4(), **extracted.model_dump(exclude={"document_id"}))
    extracted_repository.get_by_document_id.return_value = extracted_model
    normalized_repository = AsyncMock()
    await JDNormalizationService(documents, extracted_repository, normalized_repository).normalize_document(document_id)
    normalized = normalized_repository.upsert.await_args.args[0]

    assert normalized.job_title == "Software Engineer"
    assert normalized.required_skills == extracted.required_skills
    assert normalized.preferred_skills == extracted.preferred_skills
    assert normalized.education_disciplines == extracted.education_disciplines
    assert len(normalized.responsibilities) == 10
    assert normalized.experience_requirements[0].minimum_months == 0
    assert normalized.experience_requirements[0].maximum_months == 24
    assert normalized.keywords == extracted.keywords


class RecoveryAI:
    def __init__(self): self.calls = 0
    async def extract(self, text):
        self.calls += 1
        return {"job_title": "Recovered Engineer", "domain": "Wrong Domain", "required_skills": ["Wrong Skill"]}


class UnexpectedAI:
    async def extract(self, text):
        raise AssertionError("AI must not run when deterministic extraction is complete")


@pytest.mark.asyncio
async def test_ai_only_fills_missing_fields_and_never_overwrites_deterministic_values() -> None:
    text = """REQUIRED SKILLS\n- Python\nEDUCATION\n- Bachelor's degree\nEXPERIENCE\n1-2 years experience in software development\nRESPONSIBILITIES\n- Develop reliable software applications for customers."""
    document_id, documents, parsed, extracted_repository = repositories(text)
    recovery = RecoveryAI()
    await JDExtractionService(documents, parsed, extracted_repository, recovery).extract_document(document_id)
    extracted = extracted_repository.upsert.await_args.args[0]
    assert recovery.calls == 1
    assert extracted.job_title == "Recovered Engineer"
    assert extracted.domain == "Software Engineering"
    assert extracted.required_skills == ["Python"]


@pytest.mark.asyncio
async def test_ai_is_not_called_when_important_deterministic_fields_are_complete() -> None:
    document_id, documents, parsed, extracted_repository = repositories()
    await JDExtractionService(documents, parsed, extracted_repository, UnexpectedAI()).extract_document(document_id)
    extracted_repository.upsert.assert_awaited_once()
