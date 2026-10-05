from types import SimpleNamespace
from app.services.normalizers.resume_normalizer import ResumeNormalizer


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
