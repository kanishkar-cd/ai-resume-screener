from types import SimpleNamespace
from uuid import uuid4

from app.schemas.normalized_info import CanonicalProjectItem, NormalizedResumeCreate
from app.services.normalizers.resume_normalizer import ResumeNormalizer


def test_resume_with_projects_normalization():
    projects_input = [
        {
            "name": "AI Resume Screener",
            "description": "Built a resume matching system",
            "technologies": ["Python", "FastAPI", "PostgreSQL"],
        }
    ]
    extracted = SimpleNamespace(
        skills=["Python"],
        education=[],
        companies=[],
        designation=None,
        experience=[],
        projects=projects_input,
        phone=None,
        email=None,
        location=None,
        languages=[],
        certifications=[],
    )
    result = ResumeNormalizer().normalize(extracted)
    assert "projects" in result
    assert len(result["projects"]) == 1
    p = result["projects"][0]
    assert p["name"] == "AI Resume Screener"
    assert p["description"] == "Built a resume matching system"
    assert p["technologies"] == ["Python", "FastAPI", "PostgreSQL"]


def test_resume_without_projects_normalization():
    extracted = SimpleNamespace(
        skills=["Python"],
        education=[],
        companies=[],
        designation=None,
        experience=[],
        projects=[],
        phone=None,
        email=None,
        location=None,
        languages=[],
        certifications=[],
    )
    result = ResumeNormalizer().normalize(extracted)
    assert "projects" in result
    assert result["projects"] == []


def test_multiple_projects_normalization():
    projects_input = [
        {
            "name": "Project Alpha",
            "description": "Alpha service",
            "technologies": ["React.js", "Node.js"],
        },
        {
            "name": "Project Beta",
            "description": "Beta microservice",
            "technologies": ["Go", "Docker", "Kubernetes"],
        },
    ]
    extracted = SimpleNamespace(
        skills=["React", "Go"],
        education=[],
        companies=[],
        designation=None,
        experience=[],
        projects=projects_input,
        phone=None,
        email=None,
        location=None,
        languages=[],
        certifications=[],
    )
    result = ResumeNormalizer().normalize(extracted)
    assert len(result["projects"]) == 2
    assert result["projects"][0]["name"] == "Project Alpha"
    assert result["projects"][0]["technologies"] == ["React", "Node.js"]
    assert result["projects"][1]["name"] == "Project Beta"
    assert result["projects"][1]["technologies"] == ["Go", "Docker", "Kubernetes"]


def test_normalized_resume_create_schema_accepts_projects():
    doc_id = uuid4()
    ext_id = uuid4()
    norm_create = NormalizedResumeCreate(
        document_id=doc_id,
        extracted_resume_id=ext_id,
        skills=["Python"],
        projects=[
            CanonicalProjectItem(
                name="AI Resume Screener",
                description="Built a resume matching system",
                technologies=["Python", "FastAPI", "PostgreSQL"],
            )
        ],
        normalization_metadata={
            "ruleset_version": "1.0.0",
            "normalized_at": "2026-08-30T10:00:00Z",
            "changes": [],
            "warnings": [],
            "field_confidence": {},
        },
        ruleset_version="1.0.0",
    )
    dumped = norm_create.model_dump(mode="json")
    assert "projects" in dumped
    assert len(dumped["projects"]) == 1
    assert dumped["projects"][0]["name"] == "AI Resume Screener"
    assert dumped["projects"][0]["technologies"] == ["Python", "FastAPI", "PostgreSQL"]
