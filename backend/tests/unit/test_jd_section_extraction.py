import pytest
from app.services.jd_extraction_service import _split_sections, _canonical_skills
from app.services.normalizers.job_description_normalizer import JobDescriptionNormalizer


def test_scenario_1_required_plus_good_to_have():
    jd_text = """
    Software Engineer - Fresher
    
    Required Technical Skills:
    - Java, Python, C++, or JavaScript
    - Object-Oriented Programming
    - Data Structures and Algorithms
    - HTML, CSS, JavaScript
    - RESTful APIs and JSON
    - SQL, MySQL/PostgreSQL
    - Git and GitHub
    - Software Testing and Debugging

    Good-to-Have Skills:
    - React / Angular
    - Spring Boot / FastAPI / Node.js
    - Docker
    - Postman
    - CI/CD
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "Java" in req
    assert "Python" in req
    assert "C++" in req
    assert "JavaScript" in req
    assert "Docker" in pref
    assert "Postman" in pref
    assert "CI/CD" in pref

    # Verify no overlap
    req_keys = {s.casefold() for s in req}
    for p in pref:
        assert p.casefold() not in req_keys


def test_scenario_2_required_plus_preferred():
    jd_text = """
    Data Engineer
    
    Required Skills:
    - Python, SQL, ETL, Data Pipelines
    
    Preferred Skills:
    - Apache Spark, PySpark, Airflow, AWS S3
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "Python" in req
    assert "SQL" in req
    assert "ETL" in req
    assert "Data Pipelines" in req
    assert "Apache Spark" in pref or "PySpark" in pref
    assert "AWS S3" in pref or "Airflow" in pref


def test_scenario_3_mandatory_plus_nice_to_have():
    jd_text = """
    Mandatory Skills:
    • Python
    • PostgreSQL
    
    Nice to Have:
    • Docker
    • Kubernetes
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "Python" in req
    assert "PostgreSQL" in req
    assert "Docker" in pref
    assert "Kubernetes" in pref


def test_scenario_4_must_have_plus_optional():
    jd_text = """
    Must-Have Skills:
    - Java
    - Spring Boot
    
    Optional Skills:
    - Redis
    - Kafka
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "Java" in req
    assert "Spring Boot" in req
    assert "Redis" in pref
    assert "Kafka" in pref


def test_scenario_5_basic_plus_preferred_qualifications():
    jd_text = """
    Basic Qualifications:
    - HTML
    - CSS
    - JavaScript
    
    Preferred Qualifications:
    - React
    - TypeScript
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "HTML" in req
    assert "JavaScript" in req
    assert "React" in pref
    assert "TypeScript" in pref


def test_scenario_6_bullets_format():
    jd_text = """
    Required Technical Skills:
    • Python
    • FastAPI
    • SQL
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))

    assert "Python" in req
    assert "FastAPI" in req
    assert "SQL" in req


def test_scenario_7_prose_format():
    jd_text = """
    Required Technical Skills:
    Strong programming fundamentals in Java, Python, C++, or JavaScript.
    
    Preferred:
    Experience with React, Angular, and Docker.
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "Java" in req
    assert "Python" in req
    assert "C++" in req
    assert "JavaScript" in req
    assert "React" in pref
    assert "Docker" in pref


def test_scenario_8_preferred_skills_do_not_enter_required():
    jd_text = """
    Required Skills:
    - Python
    - SQL
    
    Good-to-Have Skills:
    - React
    - Docker
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "React" not in req
    assert "Docker" not in req
    assert "React" in pref
    assert "Docker" in pref


def test_scenario_9_required_skills_do_not_enter_preferred():
    jd_text = """
    Required Skills:
    - Python
    - SQL
    
    Preferred Skills:
    - Docker
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "Python" in req
    assert "SQL" in req
    assert "Python" not in pref
    assert "SQL" not in pref


def test_scenario_10_case_variation():
    jd_text = """
    REQUIRED TECHNICAL SKILLS:
    - Python
    
    Good-to-Have Skills:
    - Docker
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "Python" in req
    assert "Docker" in pref


def test_scenario_11_hyphen_variation():
    jd_text = """
    Must-Have Skills:
    - Python
    
    Nice-to-Have Skills:
    - Docker
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "Python" in req
    assert "Docker" in pref


def test_scenario_12_no_preferred_section():
    jd_text = """
    Required Skills:
    - Python
    - SQL
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert "Python" in req
    assert "SQL" in req
    assert pref == []


def test_scenario_13_no_required_section():
    jd_text = """
    Good-to-Have Skills:
    - React
    - Docker
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))

    assert req == []
    assert "React" in pref
    assert "Docker" in pref


def test_scenario_14_duplicate_skills_across_sections():
    jd_text = """
    Required Skills:
    - Python
    - SQL
    
    Preferred Skills:
    - Python
    - Docker
    """
    sections = _split_sections(jd_text)
    req = _canonical_skills(sections.get("required_skills", ""))
    pref = _canonical_skills(sections.get("preferred_skills", ""))
    req_keys = {s.casefold() for s in req}
    pref = [s for s in pref if s.casefold() not in req_keys]

    assert "Python" in req
    assert "Python" not in pref
    assert "Docker" in pref


def test_jd_normalization_preserves_required_and_preferred():
    class DummyExtractedJD:
        skills = ["Python", "SQL", "Docker"]
        required_skills = ["Python", "SQL"]
        preferred_skills = ["Docker"]
        education = ["Bachelor of Engineering"]
        experience = ["3 years"]
        domain = "Software Engineering"
        keywords = ["Python"]
        job_title = "Software Engineer"

    normalizer = JobDescriptionNormalizer()
    normalized = normalizer.normalize(DummyExtractedJD())

    assert "Python" in normalized["required_skills"]
    assert "SQL" in normalized["required_skills"]
    assert "Docker" in normalized["preferred_skills"]
    assert "Docker" not in normalized["required_skills"]
