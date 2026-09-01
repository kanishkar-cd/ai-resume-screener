from types import SimpleNamespace
from app.services.affinda_mapper import _map_projects, map_affinda_resume
from app.services.normalizers.resume_normalizer import ResumeNormalizer


def test_affinda_mapper_project_title_fallback():
    raw_projects = [
        {
            "projectTitle": None,
            "projectDescription": "Developed an e-commerce website using React and Node.js.",
            "technologies": "React, Node.js, Express",
        },
        {
            "projectTitle": "Smart Parking System",
            "projectDescription": "IoT based smart parking solution.",
            "technologies": ["Python", "FastAPI"],
        },
    ]
    mapped = _map_projects(raw_projects, None)
    assert len(mapped) == 2
    # First project with null title falls back cleanly to first 5 words of description
    assert mapped[0]["name"] == "Developed An E-Commerce Website Using"
    assert mapped[0]["technologies"] == ["React", "Node.js", "Express"]

    # Second project with explicit title preserves explicit title
    assert mapped[1]["name"] == "Smart Parking System"
    assert mapped[1]["technologies"] == ["Python", "FastAPI"]


def test_affinda_mapper_candidate_name_and_contact():
    data = {
        "candidateName": {"firstName": "Alice", "middleName": "M.", "familyName": "Smith"},
        "email": ["alice.smith@example.com"],
        "phoneNumber": [{"formattedNumber": "+1-555-0199"}],
        "skill": [{"name": "Python"}, {"name": "FastAPI"}],
        "language": [{"name": "English"}, {"name": "Spanish"}],
        "certification": [{"name": "AWS Certified Developer"}],
        "education": [{"educationAccreditation": "B.S.", "educationOrganization": "MIT", "educationMajor": ["Computer Science"]}],
        "workExperience": [],
        "project": [],
    }
    extracted, normalized = map_affinda_resume(data, provider_id="test-doc-id")
    assert extracted["candidate_name"] == "Alice M. Smith"
    assert extracted["email"] == "alice.smith@example.com"
    assert extracted["phone"] == "+1-555-0199"
    assert "Python" in extracted["skills"]
    assert "English" in extracted["languages"]
    assert "AWS Certified Developer" in extracted["certifications"]
    # Fresher candidate without workExperience keeps experience empty
    assert extracted["experience"] == []
    assert normalized["experience"] == []


def test_phase2_technology_normalization_remains_intact():
    raw_projects = [
        {
            "projectTitle": "AI Resume Screener",
            "projectDescription": "Built matching engine",
            "technologies": "Python, FastAPI, PostgreSQL",
        }
    ]
    mapped = _map_projects(raw_projects, None)
    assert mapped[0]["technologies"] == ["Python", "FastAPI", "PostgreSQL"]
    assert mapped[0]["technologies"] != ["P", "y", "t", "h", "o", "n"]


def test_normalization_preserves_all_fields():
    extracted = SimpleNamespace(
        candidate_name="Jane Doe",
        skills=["python", "fastapi"],
        education=[{"degree": "Bachelor of Science", "field_of_study": "CS", "institution": "Stanford"}],
        companies=["Google"],
        designation="Software Engineer",
        experience=[{"company": "Google", "title": "Software Engineer", "job_title": "Software Engineer", "duration": "2022-Present", "is_current": True}],
        projects=[{"name": "AI Screener", "description": "Parsing tool", "technologies": ["Python", "FastAPI"]}],
        phone="+15550199",
        email="jane@example.com",
        location="San Francisco, CA",
        languages=["English"],
        certifications=["AWS Certified Solution Architect"],
    )
    result = ResumeNormalizer().normalize(extracted)
    assert "Python" in result["skills"]
    assert result["job_titles"] == ["Software Engineer"]
    assert result["phone"] == "+15550199"
    assert result["email"] == "jane@example.com"
    assert "English" in result["languages"]
    assert "AWS Certified Solutions Architect" in result["certifications"] or "AWS Certified Solution Architect" in result["certifications"]
    assert len(result["projects"]) == 1
    assert result["projects"][0]["name"] == "AI Screener"
