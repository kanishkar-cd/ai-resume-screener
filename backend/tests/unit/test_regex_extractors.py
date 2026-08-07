from app.services.extractors.job_extractor import JobDescriptionExtractor
from app.services.extractors.resume_extractor import ResumeExtractor
from app.services.pipeline.extraction_pipeline import EMAIL_PATTERN, PHONE_PATTERN, URL_PATTERN


def test_contact_patterns_extract_supported_formats() -> None:
    text = "Jane Doe jane.doe@example.com +1-555-0199 https://example.com/profile"
    assert EMAIL_PATTERN.search(text).group(0) == "jane.doe@example.com"
    assert PHONE_PATTERN.search(text).group(0) == "+1-555-0199"
    assert URL_PATTERN.search(text).group(0) == "https://example.com/profile"


def test_resume_extraction_returns_structured_fields_and_confidence() -> None:
    result = ResumeExtractor().extract("""Jane Doe
Backend Engineer
Email: jane@example.com
Location: Bengaluru, India
SKILLS
Python, FastAPI, PostgreSQL, Docker
EDUCATION
Bachelor of Science, Example University, Computer Science, 2020
EXPERIENCE
Backend Engineer at Acme Corp | 2021 - Present
- Built FastAPI services
LANGUAGES
English, Hindi
""")
    assert result["candidate_name"] == "Jane Doe"
    assert result["email"] == "jane@example.com"
    assert "Python" in result["skills"]
    assert result["experience"][0]["company"] == "Acme Corp"
    assert result["confidence_scores"]["email"] == 0.98


def test_job_description_extraction_returns_requirements() -> None:
    result = JobDescriptionExtractor().extract("""Backend Software Engineer
RESPONSIBILITIES
- Build FastAPI services
REQUIREMENTS
Python, PostgreSQL, Docker and 5+ years of experience
EDUCATION
Bachelor of Science required
""")
    assert result["domain"] == "Software Engineering"
    assert "Python" in result["skills"]
    assert result["experience"] == ["5+ years of experience"]
    assert result["responsibilities"] == ["Build FastAPI services"]
