from types import SimpleNamespace

from app.services.normalizers.resume_normalizer import ResumeNormalizer


def test_complete_resume_normalization() -> None:
    extracted = SimpleNamespace(
        skills=["python", "PYTHON", "postgres"],
        education=[{"degree": "B.E.", "field_of_study": "Computer Science", "institution": "Example University", "year": "2020"}],
        companies=["Acme Corp."], designation="C++ Developer",
        experience=[{"company": "Acme Corp.", "title": "Sr. Backend Dev", "duration": "2021 - Present", "responsibilities": []}],
        phone="+91-98765-43210", email="JANE.DOE@EXAMPLE.COM ", location="Bangalore",
        languages=["Eng", "Hindi"], certifications=["PMP"],
    )
    result = ResumeNormalizer().normalize(extracted)
    assert result["skills"] == ["Python", "PostgreSQL"]
    assert result["education"][0]["degree"] == "Bachelor of Engineering"
    assert result["companies"] == ["Acme Corporation"]
    assert result["job_titles"] == ["Software Engineer", "Senior Backend Engineer"]
    assert result["experience"][0]["is_current"] is True
    assert result["phone"] == "+919876543210"
    assert result["email"] == "jane.doe@example.com"
    assert result["locations"][0]["country_code"] == "IN"
    assert result["languages"] == ["English", "Hindi"]
    assert result["certifications"] == ["Project Management Professional (PMP)"]
    assert result["ruleset_version"] == "1.0.0"
