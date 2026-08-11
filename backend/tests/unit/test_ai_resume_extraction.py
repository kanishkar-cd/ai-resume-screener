import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.models.document import DocumentTypeEnum
from app.services.extraction_service import ExtractionService
from app.services.extractors.ai_resume_extractor import AIResumeExtractor
from app.services.extractors.resume_merge import merge_resume_extractions


def deterministic_result() -> dict:
    return {
        "candidate_name": "Jane Doe",
        "email": "jane@example.com",
        "phone": None,
        "designation": None,
        "location": None,
        "skills": ["JavaScript", "HTML"],
        "education": [],
        "experience": [],
        "projects": [{"name": "Training Website", "description": None, "technologies": ["HTML"]}],
        "certifications": [],
        "companies": [],
        "languages": [],
        "confidence_scores": {"candidate_name": 1.0},
        "raw_metadata": {"method": "deterministic_hierarchical_rules"},
    }


def test_merge_fills_missing_fields_preserves_deterministic_values_and_deduplicates() -> None:
    ai = {
        "candidate_name": "Incorrect Name",
        "designation": "Software Engineer",
        "skills": ["javascript", "IoT", "PLC Programming"],
        "experience": [{"company": "ABC Technologies", "designation": "Engineer", "responsibilities": ["Built controls"]}],
        "projects": [
            {"name": "Training Website", "description": "Training portal", "technologies": ["JavaScript"]},
            {"name": "Smart Parking System", "description": "IoT parking", "technologies": ["IoT", "PLC Programming"]},
            {"name": "E-commerce Platform", "description": "Storefront", "technologies": ["JavaScript"]},
        ],
        "languages": ["English", "Tamil"],
    }
    merged = merge_resume_extractions(deterministic_result(), ai)
    assert merged["candidate_name"] == "Jane Doe"
    assert merged["designation"] == "Software Engineer"
    assert [skill.casefold() for skill in merged["skills"]].count("javascript") == 1
    assert merged["skills"][-2:] == ["IoT", "PLC Programming"]
    assert len(merged["projects"]) == 3
    assert merged["projects"][0]["description"] == "Training portal"
    assert merged["projects"][0]["technologies"] == ["HTML", "JavaScript"]


@pytest.mark.asyncio
async def test_ai_extractor_returns_strict_existing_structure(monkeypatch) -> None:
    response_body = {
        "choices": [{"message": {"content": json.dumps({
            "candidate_name": "Jane Doe", "email": None, "phone": None,
            "designation": "Engineer", "location": None, "skills": ["IoT"],
            "education": [], "experience": [],
            "projects": [{"name": "Smart Parking", "description": None, "technologies": ["IoT"]}],
            "certifications": [], "companies": [], "languages": ["English"],
        })}}]
    }

    class Response:
        def raise_for_status(self): return None
        def json(self): return response_body

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, *args, **kwargs): return Response()

    monkeypatch.setattr("app.services.extractors.ai_resume_extractor.httpx.AsyncClient", Client)
    settings = Settings(_env_file=None, GROQ_API_KEY="test-key", ENABLE_AI_RESUME_EXTRACTION=True)
    result = await AIResumeExtractor(settings).extract("Jane Doe\nEngineer\nIoT")
    assert result is not None
    assert result["designation"] == "Engineer"
    assert result["projects"][0]["name"] == "Smart Parking"


class Documents:
    def __init__(self): self.updates = []
    async def get_document(self, document_id): return SimpleNamespace(document_type=DocumentTypeEnum.RESUME)
    async def update_processing(self, document_id, stage, status, error_message=None, **kwargs): self.updates.append(stage)


class Parsed:
    async def get_by_document_id(self, document_id):
        return SimpleNamespace(normalized_text="Jane Doe\njane@example.com\nSKILLS\nJavaScript")


class Extractions:
    resume = None
    async def create_or_update_resume(self, data, **kwargs): self.resume = data


class RecoveringAI:
    async def extract(self, text): return {"designation": "Software Engineer", "skills": ["IoT"]}


class FailingAI:
    async def extract(self, text): raise ValueError("malformed provider response")


@pytest.mark.asyncio
async def test_service_merges_ai_recovery_without_replacing_deterministic_data() -> None:
    repository = Extractions()
    await ExtractionService(Documents(), Parsed(), repository, RecoveringAI()).extract_document_data(uuid4())
    assert repository.resume.candidate_name == "Jane Doe"
    assert repository.resume.designation == "Software Engineer"
    assert "JavaScript" in repository.resume.skills and "IoT" in repository.resume.skills


@pytest.mark.asyncio
async def test_provider_or_malformed_response_failure_falls_back_to_deterministic() -> None:
    repository = Extractions()
    await ExtractionService(Documents(), Parsed(), repository, FailingAI()).extract_document_data(uuid4())
    assert repository.resume.candidate_name == "Jane Doe"
    assert repository.resume.email == "jane@example.com"
    assert repository.resume.raw_metadata["method"] == "deterministic_hierarchical_rules"
