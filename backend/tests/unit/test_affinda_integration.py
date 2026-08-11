from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.document import DocumentTypeEnum, ProcessingStageEnum, ProcessingStatusEnum
from app.schemas.document import ProcessingStage
from app.services.affinda_mapper import map_affinda_resume
from app.services.extraction_service import ExtractionService
from app.services.jd_extraction_service import JDExtractionService
from app.services.parsing_service import ParsingService
from app.services.normalization_service import NormalizationService


AFFINDA_RESUME = {
    "candidateName": {"firstName": "Jane", "middleName": None, "familyName": "Doe"},
    "email": ["jane@example.com"],
    "phoneNumber": [{"formattedNumber": "+1 555 0100"}],
    "skill": [{"name": "Python (Programming Language)"}, {"name": "SQL"}],
    "education": [{"educationAccreditation": "Bachelor of Technology", "educationMajor": ["Computer Science"], "educationOrganization": "Example University"}],
    "workExperience": [{"workExperienceOrganization": "Example Co", "workExperienceJobTitle": "Engineer", "workExperienceDates": {"start": {"date": "2022-01-01"}, "end": {"date": "2023-07-01", "isCurrent": False}}}],
    "project": [{"projectTitle": "Portal", "projectDescription": "A portal", "technologies": [{"name": "Python (Programming Language)"}]}],
    "certifications": [{"name": "AWS Certified Developer"}],
    "language": [{"name": "English"}],
}


class FakeAffinda:
    configured = True

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.resume_calls = 0
        self.jd_calls = 0

    async def parse_resume(self, *args):
        self.resume_calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        return {"data": {**AFFINDA_RESUME, "rawText": "Jane Doe\nPython"}, "meta": {"identifier": "provider-id"}}

    async def parse_job_description(self, *args):
        self.jd_calls += 1
        raise RuntimeError("provider unavailable")


class FakeStorage:
    def resolve_file(self, path):
        return Path(__file__)


class Documents:
    def __init__(self, document): self.document = document; self.updates = []
    async def get_document(self, document_id): return self.document
    async def update_processing(self, document_id, stage, status, error_message=None, **kwargs): self.updates.append((stage, status)); return self.document
    async def update_status(self, document_id, status, metadata=None, **kwargs):
        self.updates.append((None, status)); self.document.processing_status = ProcessingStatusEnum(status.value); self.document.processing_stage = ProcessingStageEnum.PARSING; self.document.metadata_json = metadata or {}; return self.document


class Parsed:
    async def get_by_document_id(self, document_id): return SimpleNamespace(normalized_text="Fallback Person\nSKILLS\nJava", raw_text="Job Title: Engineer\nSkills: Python", word_count=6)


class ParsedCapture(Parsed):
    def __init__(self): self.saved = None
    async def upsert(self, value, **kwargs): self.saved = value


class Extractions:
    def __init__(self): self.resume = None
    async def create_or_update_resume(self, data, **kwargs): self.resume = data
    async def create_or_update_job_description(self, data, **kwargs): raise AssertionError


class AffindaExtractionRead:
    def __init__(self, normalized): self.id = uuid4(); self.raw_metadata = {"provider": "affinda", "affinda_normalized_profile": normalized}
    async def get_resume_by_document_id(self, document_id): return self


class Normalizations:
    def __init__(self): self.resume = None
    async def create_or_update_resume(self, value, **kwargs): self.resume = value


def document(kind=DocumentTypeEnum.RESUME):
    return SimpleNamespace(id=uuid4(), document_type=kind, processing_status=ProcessingStatusEnum.PARSED, processing_stage=ProcessingStageEnum.PARSING, metadata_json={}, file_path="stored", original_filename="document.pdf", mime_type="application/pdf")


def test_affinda_resume_mapper_is_conservative_and_scoring_compatible() -> None:
    extracted, normalized = map_affinda_resume(AFFINDA_RESUME, "provider-id")
    assert extracted["candidate_name"] == "Jane Doe"
    assert normalized["skills"] == ["Python", "SQL"]
    assert normalized["experience"][0]["duration_months"] == 18
    assert normalized["education"][0]["degree"] == "Bachelor of Technology"
    assert extracted["projects"][0]["technologies"] == ["Python"]
    assert normalized["certifications"] == ["AWS Certified Developer"]
    assert extracted["raw_metadata"]["provider"] == "affinda"


def test_jegadhees_projects_and_skill_aliases_are_preserved() -> None:
    project_descriptions = [
        "Developed a web platform to track and reduce carbon footprint through eco-friendly activities. Integrated with cottage industries to reward sustainable habits and promote eco-conscious products. Recognized among the top 10 of 230+ projects at the college expo.",
        "Developed a full-stack home service booking application that allows users to book services like cleaning and maintenance online. Built the frontend using React.js and the backend using Node.js and Express.js, with MongoDB used for storing user and booking information. Implemented features such as user login, service selection, and booking management with a responsive interface.",
        "Developed a cybersecurity-focused web app to detect scam URLs, phishing links, and unsafe redirections using networking protocols, threat intelligence APIs, and domain analysis. Integrated real-time scam keyword detection to enhance online safety awareness and secure browsing. Demonstrates strong skills in cybersecurity, network security, and web-based threat detection.",
        "Developed a real-time groundwater monitoring app that visualizes DWLR sensor data, tracks water level fluctuations, and provides predictive insights through interactive dashboards to support efficient and sustainable water management.",
    ]
    raw_titles = ["SustainTrack.me", "KeeHome-", "PhisScan", "Aquanta"]
    titles = ["SustainTrack.me", "KeeHome", "PhisScan", "Aquanta"]
    # Real Affinda rawText structure: page layout is flattened, the word
    # "projects" occurs in internship prose before the actual uppercase
    # heading, and lowercase "skills" occurs inside a project description.
    source = (
        "Completed a hands-on MERN stack internship with RESTful APIs, "
        "strengthening my ability to develop and deploy real-world web projects. "
        "Cybersecurity Intern completed practical work. "
        "PROJECTS "
        + " ".join(
            f"{title} 2025 {description}"
            for title, description in zip(raw_titles, project_descriptions, strict=True)
        )
        + " CERTIFICATIONS Networking Basics CISCO 2025 "
        "ACHIEVEMENTS IEEE Competition CODING PROFILES Leetcode SKILLS DSA"
    )
    payload = {
        "candidateName": {"firstName": "JEGADHEES", "familyName": "J"},
        "skill": [
            {"name": "Python (Programming Language)"},
            {"name": "Git (Version Control System)"},
            {"name": "Cascading Style Sheets (CSS)"},
            {"name": "React.js (Javascript Library)"},
            {"name": "Node.js (Javascript Library)"},
            {"name": "Express.js (Javascript Library)"},
            {"name": "Object-Oriented Programming (OOP)"},
            {"name": "Application Programming Interface (API)"},
            {"name": "HTML Scripting"},
            {"name": "Data Structures"},
        ],
        "project": [
            {
                "projectTitle": title,
                "projectDescription": "\n".join(project_descriptions) if index == 0 else None,
                "technologies": [{"name": "Python (Programming Language)"}] if index == 0 else None,
            }
            for index, title in enumerate(raw_titles)
        ],
    }

    extracted, normalized = map_affinda_resume(payload, "provider-id", source)

    assert [project["name"] for project in extracted["projects"]] == titles
    assert [project["description"] for project in extracted["projects"]] == project_descriptions
    assert extracted["projects"][0]["technologies"] == ["Python"]
    assert all(not project["technologies"] for project in extracted["projects"][1:])
    assert normalized["skills"] == [
        "Python", "Git", "CSS", "React.js", "Node.js", "Express.js",
        "Object-Oriented Programming", "REST API", "HTML",
        "Data Structures and Algorithms",
    ]


@pytest.mark.asyncio
async def test_affinda_is_primary_at_parse_boundary() -> None:
    doc = document()
    parsed = ParsedCapture()
    provider = FakeAffinda()
    await ParsingService(Documents(doc), parsed, FakeStorage(), provider).parse_document(doc.id)
    assert provider.resume_calls == 1
    assert parsed.saved.raw_text == "Jane Doe\nPython"
    assert doc.metadata_json["document_intelligence_provider"] == "affinda"
    assert doc.metadata_json["affinda_payload"]["meta"] == {"identifier": "provider-id"}


@pytest.mark.asyncio
async def test_affinda_parse_failure_uses_local_parser() -> None:
    doc = document()
    doc.original_filename = "resume.txt"
    doc.mime_type = "text/plain"
    parsed = ParsedCapture()
    provider = FakeAffinda(fail=True)
    await ParsingService(Documents(doc), parsed, FakeStorage(), provider).parse_document(doc.id)
    assert provider.resume_calls == 1
    assert parsed.saved.raw_text
    assert doc.metadata_json["document_intelligence_provider"] == "local"


@pytest.mark.asyncio
async def test_affinda_resume_success_is_primary() -> None:
    doc = document()
    repo = Extractions()
    provider = FakeAffinda()
    result = await ExtractionService(Documents(doc), Parsed(), repo, affinda_service=provider, storage=FakeStorage()).extract_document_data(doc.id)
    assert result.processing_stage == ProcessingStage.COMPLETED
    assert provider.resume_calls == 1
    assert repo.resume.candidate_name == "Jane Doe"
    assert repo.resume.skills == ["Python", "SQL"]
    assert repo.resume.raw_metadata["provider"] == "affinda"


@pytest.mark.asyncio
async def test_affinda_profile_bypasses_local_semantic_normalizer() -> None:
    doc = document()
    _, normalized = map_affinda_resume(AFFINDA_RESUME, "provider-id")
    output = Normalizations()
    await NormalizationService(Documents(doc), AffindaExtractionRead(normalized), output).normalize_document_data(doc.id)
    assert output.resume.skills == ["Python", "SQL"]
    assert output.resume.experience[0].duration_months == 18


@pytest.mark.asyncio
async def test_affinda_resume_failure_uses_existing_extractor() -> None:
    doc = document()
    repo = Extractions()
    provider = FakeAffinda(fail=True)
    await ExtractionService(Documents(doc), Parsed(), repo, affinda_service=provider, storage=FakeStorage()).extract_document_data(doc.id)
    assert provider.resume_calls == 1
    assert repo.resume.raw_metadata.get("provider") != "affinda"
    assert "Java" in repo.resume.skills


@pytest.mark.asyncio
async def test_affinda_jd_failure_uses_existing_jd_extractor() -> None:
    doc = document(DocumentTypeEnum.JOB_DESCRIPTION)
    docs = Documents(doc)
    repo = SimpleNamespace(upsert=AsyncMock())
    provider = FakeAffinda(fail=True)
    result = await JDExtractionService(docs, Parsed(), repo, affinda_service=provider, storage=FakeStorage()).extract_document(doc.id)
    assert result.processing_stage == ProcessingStage.EXTRACTION
    assert provider.jd_calls == 1
    assert repo.upsert.await_count == 1
    assert repo.upsert.await_args.args[0].raw_metadata.get("provider") != "affinda"
