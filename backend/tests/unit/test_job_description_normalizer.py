from types import SimpleNamespace

from app.services.normalizers.job_description_normalizer import JobDescriptionNormalizer


def test_complete_job_description_normalization() -> None:
    extracted = SimpleNamespace(
        skills=["Py", "postgres"], education=["B.E."], experience=["3+ years"],
        domain="IT", keywords=["PYTHON", "C++ Developer", "software development"],
    )
    result = JobDescriptionNormalizer().normalize(extracted)
    assert result["skills"] == ["Python", "PostgreSQL"]
    assert result["degree_requirements"] == ["Bachelor of Engineering"]
    assert result["experience_requirements"][0] == {"minimum_months": 36, "maximum_months": None, "display_value": "3 years+"}
    assert result["domain"] == "Software Engineering"
    assert result["keywords"] == ["Python", "Software Engineer", "Software Engineering"]


def test_software_engineer_keyword_normalization() -> None:
    extracted = SimpleNamespace(
        skills=["C++", "SQL"], education=["Bachelor of Engineering"], experience=[],
        domain="Software Engineering", keywords=["Software Engineer", "C++", "SQL"],
    )
    result = JobDescriptionNormalizer().normalize(extracted)
    assert "Software Engineer" in result["keywords"]
    assert result["normalization_metadata"]["warnings"] == []
    assert result["normalization_metadata"]["field_confidence"].get("keywords") == 1.0

