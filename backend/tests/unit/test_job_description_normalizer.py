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
