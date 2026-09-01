import pytest
from types import SimpleNamespace
from app.services.extractors.resume_extractor import ResumeExtractor
from app.services.normalizers.resume_normalizer import ResumeNormalizer
from app.services.matching_service import EvidenceBuilder


def test_generic_non_canonical_entity_extraction():
    """Verify that arbitrary non-canonical entities survive extraction and normalization without dictionary membership."""
    sample_text = """
John Doe
Software Engineer
Email: john.doe@example.com | Phone: +1-555-0199

Skills
Tools:
ExampleToolXYZ, ExamplePlatformABC, Playwright, Postman, Vercel

Frameworks:
ExampleFramework123, React.js, Next.js

Projects
Project: Cloud Monitoring Tool
Technologies: ExampleTechFoo, ExampleTechBar, Prometheus, Grafana
Built real-time metrics dashboards.
"""
    extractor = ResumeExtractor()
    extracted = extractor.extract(sample_text)

    skills = extracted["skills"]

    # 1. Non-canonical synthetic entities must survive
    assert "ExampleToolXYZ" in skills
    assert "ExamplePlatformABC" in skills
    assert "ExampleFramework123" in skills

    # 2. Specific tools from the user test case must survive
    assert "Playwright" in skills
    assert "Postman" in skills
    assert "Vercel" in skills

    # 3. Canonical entities must also survive
    assert any("react" in s.lower() for s in skills)
    assert "Next.js" in skills

    # 4. Project technologies must survive
    assert len(extracted["projects"]) >= 1
    proj_techs = extracted["projects"][0]["technologies"]
    assert "ExampleTechFoo" in proj_techs
    assert "ExampleTechBar" in proj_techs


def test_real_candidate_resume_extraction():
    """Verify that the candidate's exact resume structure extracts all entities into runtime objects."""
    resume_text = """
Candidate Name
Email: candidate@example.com | Phone: +91 9876543210
Location: Coimbatore, India

Skills
Languages:
C++, HTML, CSS, JavaScript

Core:
Data Structures and Algorithms, OOPS, DBMS, REST APIs

Framework:
React.js, Node.js, Express.js, Next.js

Query Language:
MySQL, MongoDB

Tools:
VSCode, Canva, GitHub, Git, Postman, Vercel, Playwright

Projects
Project: Secure Voting System
Technologies: React.js, Node.js, Express.js, MongoDB, REST APIs
Built blockchain and web-based voting application.

Project: Smart Trolleys
Technologies: IoT, Embedded Systems, C++, Python
Smart shopping cart with automated billing.

Experience
Nimble Wireless
PQA Intern
Duration: 3 Months
Worked on quality assurance and API verification.

Education
Sri Eshwar College of Engineering
B.Tech (CSBS)
Year: 2025
"""
    extractor = ResumeExtractor()
    extracted_dict = extractor.extract(resume_text)

    skills = extracted_dict["skills"]

    # Verify all expected entities are extracted
    expected_skills = [
        "C++", "HTML", "CSS", "JavaScript",
        "Data Structures and Algorithms", "OOPS", "DBMS", "REST APIs",
        "React.js", "Node.js", "Express.js", "Next.js",
        "MySQL", "MongoDB",
        "VSCode", "Canva", "GitHub", "Git", "Postman", "Vercel", "Playwright"
    ]

    for expected in expected_skills:
        assert any(expected.lower() == s.lower() for s in skills), f"Missing skill: {expected} in {skills}"

    # Verify Normalization preserves non-canonical entities as preserved_unknown
    extracted_obj = SimpleNamespace(**extracted_dict)
    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(extracted_obj)

    normalized_skills = normalized["skills"]
    assert "Playwright" in normalized_skills
    assert "Postman" in normalized_skills
    assert "Vercel" in normalized_skills

    # Verify EvidenceBuilder creates Evidence with all skills
    evidence_list = EvidenceBuilder.build(extracted_obj)
    skills_evidence = next((e for e in evidence_list if e.kind == "skills"), None)
    assert skills_evidence is not None
    assert "Playwright" in skills_evidence.canonical_terms
    assert "Postman" in skills_evidence.canonical_terms
    assert "Vercel" in skills_evidence.canonical_terms
