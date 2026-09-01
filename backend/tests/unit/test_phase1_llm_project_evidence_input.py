import pytest
from types import SimpleNamespace
from app.services.matching_service import EvidenceBuilder


def test_1_project_description_reaches_evidence_text() -> None:
    """1. Project description reaches Evidence.text."""
    extracted = SimpleNamespace(
        projects=[{
            "name": "Data Pipeline",
            "description": "Engineered real-time ETL pipeline using Spark and Airflow.",
            "technologies": ["Spark", "Airflow"],
        }],
        skills=["Python"],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    project_ev = next(e for e in evidence if e.evidence_id == "project:1")
    assert "Engineered real-time ETL pipeline using Spark and Airflow." in project_ev.text


def test_2_project_technologies_reach_evidence_text() -> None:
    """2. Project technologies reach Evidence.text."""
    extracted = SimpleNamespace(
        projects=[{
            "name": "AI Screener",
            "description": "Resume matching system.",
            "technologies": ["Python", "FastAPI", "PostgreSQL"],
        }],
        skills=["Python"],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    project_ev = next(e for e in evidence if e.evidence_id == "project:1")
    assert "FastAPI" in project_ev.text
    assert "PostgreSQL" in project_ev.text
    assert project_ev.canonical_terms == ["Python", "FastAPI", "PostgreSQL"]


def test_3_project_deliverables_reach_evidence_text() -> None:
    """3. Project deliverables reach Evidence.text."""
    extracted = SimpleNamespace(
        projects=[{
            "name": "E-Commerce App",
            "description": "Online shopping store.",
            "technologies": ["React", "Node.js"],
            "deliverables": ["Delivered REST API endpoints", "Automated deployment pipeline"],
        }],
        skills=[],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    project_ev = next(e for e in evidence if e.evidence_id == "project:1")
    assert "Delivered REST API endpoints" in project_ev.text
    assert "Automated deployment pipeline" in project_ev.text


def test_4_project_highlights_reach_evidence_text() -> None:
    """4. Project highlights reach Evidence.text."""
    extracted = SimpleNamespace(
        projects=[{
            "name": "Analytics Dashboard",
            "description": "Business intelligence dashboard.",
            "technologies": ["Python", "PowerBI"],
            "highlights": ["Reduced query latency by 40%", "Processed 10M daily events"],
        }],
        skills=[],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    project_ev = next(e for e in evidence if e.evidence_id == "project:1")
    assert "Reduced query latency by 40%" in project_ev.text
    assert "Processed 10M daily events" in project_ev.text


def test_5_project_summary_reaches_evidence_text() -> None:
    """5. Project summary reaches Evidence.text."""
    extracted = SimpleNamespace(
        projects=[{
            "name": "IoT Parking System",
            "description": "Smart parking solution.",
            "technologies": ["C++", "IoT"],
            "summary": "Automated parking space detection using ultrasonic sensors.",
        }],
        skills=[],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    project_ev = next(e for e in evidence if e.evidence_id == "project:1")
    assert "Automated parking space detection using ultrasonic sensors." in project_ev.text


def test_6_project_responsibilities_reach_evidence_text() -> None:
    """6. Project responsibilities reach Evidence.text."""
    extracted = SimpleNamespace(
        projects=[{
            "name": "Cloud Infrastructure Lab",
            "description": "AWS infrastructure setup.",
            "technologies": ["Terraform", "AWS"],
            "responsibilities": ["Configured VPC peering and security groups", "Set up CloudWatch monitoring"],
        }],
        skills=[],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    project_ev = next(e for e in evidence if e.evidence_id == "project:1")
    assert "Configured VPC peering and security groups" in project_ev.text
    assert "Set up CloudWatch monitoring" in project_ev.text


def test_7_project_outcomes_reach_evidence_text() -> None:
    """7. Project outcomes reach Evidence.text."""
    extracted = SimpleNamespace(
        projects=[{
            "name": "Sales Forecast Model",
            "description": "Machine learning forecast pipeline.",
            "technologies": ["Python", "Scikit-learn"],
            "outcomes": "Achieved 95% forecast accuracy on quarterly revenue.",
        }],
        skills=[],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    project_ev = next(e for e in evidence if e.evidence_id == "project:1")
    assert "Achieved 95% forecast accuracy on quarterly revenue." in project_ev.text


def test_8_project_details_reach_evidence_text() -> None:
    """8. Project details reach Evidence.text."""
    extracted = SimpleNamespace(
        projects=[{
            "name": "FinTech Payment Gateway",
            "description": "Secure payment gateway integration.",
            "technologies": ["Go", "Stripe"],
            "details": ["Integrated Stripe Webhooks for asynchronous billing", "Implemented PCI-DSS compliance controls"],
        }],
        skills=[],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    project_ev = next(e for e in evidence if e.evidence_id == "project:1")
    assert "Integrated Stripe Webhooks for asynchronous billing" in project_ev.text
    assert "Implemented PCI-DSS compliance controls" in project_ev.text


def test_9_missing_optional_fields_do_not_break_evidence_construction() -> None:
    """9. Missing optional fields do not break evidence construction."""
    extracted = SimpleNamespace(
        projects=[
            {"name": "Minimal Project A"},
            {"name": "Minimal Project B", "description": "Only description."},
            {"name": "Minimal Project C", "technologies": ["Python"]},
        ],
        skills=[],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    proj_ids = [e.evidence_id for e in evidence if e.kind == "project"]
    assert proj_ids == ["project:1", "project:2", "project:3"]
    assert evidence[0].text == "Minimal Project A"
    assert evidence[1].text == "Minimal Project B Only description."
    assert evidence[2].text == "Minimal Project C Python"


def test_10_skills1_not_used_as_project_evidence() -> None:
    """10. skills:1 is still NOT used as project evidence."""
    extracted = SimpleNamespace(
        projects=[{
            "name": "Standalone Web App",
            "description": "Full-stack application.",
            "technologies": ["React"],
        }],
        skills=["Python", "SQL", "Docker", "Airflow", "PySpark"],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    skills_ev = next(e for e in evidence if e.evidence_id == "skills:1")
    project_ev = next(e for e in evidence if e.evidence_id == "project:1")

    assert skills_ev.kind == "skills"
    assert project_ev.kind == "project"

    # skills:1 text contains Python, SQL, Docker, Airflow, PySpark
    assert "PySpark" in skills_ev.text
    # project:1 text contains only project evidence, NOT resume.skills
    assert "PySpark" not in project_ev.text
