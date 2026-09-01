import pytest
from app.services.affinda_mapper import map_affinda_resume
from app.services.extractors.resume_extractor import ResumeExtractor
from app.services.normalizers.resume_normalizer import ResumeNormalizer


def test_1_one_experience_with_multiple_bullets() -> None:
    text = """Cloud Destinations
Software Engineer
June 2025 – Present
- Developed scalable microservices using Python and FastAPI.
- Implemented PostgreSQL database schemas and optimized slow queries.
- Built automated CI/CD deployment workflows with Docker and GitHub Actions.
"""
    result = ResumeExtractor()._experience(text)
    assert len(result) == 1
    exp = result[0]
    assert exp["company"] == "Cloud Destinations"
    assert exp["title"] == "Software Engineer"
    assert exp["is_current"] is True
    assert "June 2025" in exp["start_date"] or "2025" in exp["start_date"]
    assert "FastAPI" in exp["description"]
    assert "PostgreSQL" in exp["description"]
    assert "GitHub Actions" in exp["description"]
    assert len(exp["responsibilities"]) >= 3


def test_2_two_separate_experiences() -> None:
    text = """TechNova Solutions
Software Engineer
2023 – Present
- Maintained backend cloud services.

CodeBridge Technologies
Junior Software Engineer
2022 – 2023
- Built frontend interfaces with React.
"""
    result = ResumeExtractor()._experience(text)
    assert len(result) == 2
    assert result[0]["company"] == "TechNova Solutions"
    assert result[0]["title"] == "Software Engineer"
    assert result[0]["is_current"] is True

    assert result[1]["company"] == "CodeBridge Technologies"
    assert result[1]["title"] == "Junior Software Engineer"
    assert result[1]["is_current"] is False


def test_3_internship_plus_fulltime_employment() -> None:
    text = """ABC Corp
Software Engineer Intern
May 2024 to July 2024
- Worked on internal tools.

XYZ Solutions
Software Engineer
Aug 2024 to Present
- Leading backend features.
"""
    result = ResumeExtractor()._experience(text)
    assert len(result) == 2
    assert result[0]["employment_type"] == "Internship"
    assert result[0]["company"] == "ABC Corp"
    assert result[0]["is_current"] is False

    assert result[1]["employment_type"] == "Full-time"
    assert result[1]["company"] == "XYZ Solutions"
    assert result[1]["is_current"] is True


def test_4_experience_ending_in_present_never_assigns_present_as_company() -> None:
    text = """Cloud Destinations
Associate Software Engineer
June 2026 – Present
- Working on BA Accelerator, an internal initiative.
"""
    result = ResumeExtractor()._experience(text)
    assert len(result) == 1
    assert result[0]["company"] == "Cloud Destinations"
    assert result[0]["company"] != "Present"
    assert result[0]["title"] == "Associate Software Engineer"
    assert result[0]["is_current"] is True


def test_5_missing_company_preserves_title_and_dates() -> None:
    text = """Role : Freelance Backend Developer
01/2023 – 12/2023
- Developed custom payment gateway integration.
"""
    result = ResumeExtractor()._experience(text)
    assert len(result) == 1
    assert result[0]["company"] is None
    assert result[0]["title"] == "Freelance Backend Developer"
    assert result[0]["employment_type"] == "Freelance"
    assert result[0]["start_date"] == "01/2023"
    assert result[0]["end_date"] == "12/2023"


def test_6_missing_title_preserves_company_and_dates() -> None:
    text = """Nimble Wireless Private Ltd
01/2024 – 06/2024
- Conducted regression testing and automated QA scripts.
"""
    result = ResumeExtractor()._experience(text)
    assert len(result) == 1
    assert result[0]["company"] == "Nimble Wireless Private Ltd"
    assert result[0]["title"] is None
    assert result[0]["start_date"] == "01/2024"
    assert result[0]["end_date"] == "06/2024"


def test_7_missing_dates_preserves_company_and_title() -> None:
    text = """Technology Solutions Pvt. Ltd.
Role : Intern
- Assisted engineering team with REST APIs.
"""
    result = ResumeExtractor()._experience(text)
    assert len(result) == 1
    assert result[0]["company"] == "Technology Solutions Pvt. Ltd."
    assert result[0]["title"] == "Intern"
    assert result[0]["employment_type"] == "Internship"
    assert result[0]["start_date"] is None
    assert result[0]["end_date"] is None


def test_8_multiple_experiences_from_affinda_mapped_and_normalized() -> None:
    payload = {
        "candidateName": {"raw": "Alexander Pierce"},
        "workExperience": [
            {
                "workExperienceOrganization": "TechNova Solutions",
                "workExperienceJobTitle": "Senior Software Engineer",
                "workExperienceDates": {
                    "start": {"date": "2023-01-01"},
                    "end": {"isCurrent": True},
                },
                "workExperienceType": {"label": "Full-time"},
                "workExperienceDescription": "Leading cloud architecture and Python services.",
                "workExperienceResponsibilities": ["Leading cloud architecture", "Python services"],
            },
            {
                "workExperienceOrganization": "CodeBridge Technologies",
                "workExperienceJobTitle": "Software Engineer Intern",
                "workExperienceDates": {
                    "start": {"date": "2022-01-01"},
                    "end": {"date": "2022-12-31", "isCurrent": False},
                },
                "workExperienceType": {"label": "Internship"},
                "workExperienceDescription": "Built REST APIs and frontend components.",
                "workExperienceResponsibilities": ["Built REST APIs", "Frontend components"],
            },
        ],
    }

    extracted, normalized = map_affinda_resume(payload, "provider-1")

    assert len(extracted["experience"]) == 2
    assert len(normalized["experience"]) == 2

    assert extracted["experience"][0]["company"] == "TechNova Solutions"
    assert extracted["experience"][0]["title"] == "Senior Software Engineer"
    assert extracted["experience"][0]["employment_type"] == "Full-time"
    assert extracted["experience"][0]["is_current"] is True
    assert extracted["experience"][0]["responsibilities"] == ["Leading cloud architecture", "Python services"]

    assert normalized["experience"][0]["company"] == "TechNova Solutions"
    assert normalized["experience"][0]["job_title"] == "Senior Software Engineer"
    assert normalized["experience"][0]["is_current"] is True
    assert normalized["experience"][0]["description"] == "Leading cloud architecture and Python services."

    assert extracted["experience"][1]["company"] == "CodeBridge Technologies"
    assert extracted["experience"][1]["employment_type"] == "Internship"
    assert extracted["experience"][1]["is_current"] is False


def test_9_affinda_structured_data_vs_local_fallback() -> None:
    # When Affinda has empty workExperience, local fallback parses source text
    empty_payload = {
        "candidateName": {"raw": "Muthu Visalakshi M"},
        "workExperience": [],
    }
    source_text = """Muthu Visalakshi M
muthu@example.com
9876543210

WORK EXPERIENCE
Cloud Destinations, Coimbatore
Role : Associate Software Engineer
June 2026 – Present
- Working on BA Accelerator, contributing to core AI agent framework.
- Collaborating with engineering team to design agent-based automation.

PROJECTS
Project: Smart Health
- Built health app using React.
"""
    extracted, normalized = map_affinda_resume(empty_payload, "provider-2", source_text=source_text)

    assert len(extracted["experience"]) == 1
    assert len(normalized["experience"]) == 1

    exp = extracted["experience"][0]
    assert exp["company"] == "Cloud Destinations"
    assert exp["company"] != "Present"
    assert exp["title"] == "Associate Software Engineer"
    assert exp["is_current"] is True
    assert "BA Accelerator" in exp["description"]


def test_10_project_must_not_become_experience() -> None:
    text = """Alex Smith
alex@example.com

PROJECTS
Project: Smart Health Tracker
- Built React frontend and Python FastAPI backend for real-time fitness metrics.
- Integrated SQLite database and Docker containerization.

INTERNSHIP
Customer Centria, Coimbatore
Role : Database Management Intern
08/2025 – 10/2025
- Managed cloud databases and SQL querying.
"""
    extractor = ResumeExtractor()
    result = extractor.extract(text)

    assert len(result["projects"]) == 1
    assert result["projects"][0]["name"] == "Smart Health Tracker"

    assert len(result["experience"]) == 1
    assert result["experience"][0]["company"] == "Customer Centria"
    assert result["experience"][0]["company"] != "Smart Health Tracker"


def test_11_complete_description_preservation_in_normalization() -> None:
    class DummyExtracted:
        skills = ["Python", "FastAPI"]
        education = []
        experience = [
            {
                "company": "Cloud Destinations",
                "title": "Software Engineer",
                "employment_type": "Full-time",
                "start_date": "2025-06-01",
                "end_date": None,
                "is_current": True,
                "description": "Bullet 1. Bullet 2. Bullet 3.",
                "responsibilities": ["Bullet 1", "Bullet 2", "Bullet 3"],
                "location": "Coimbatore",
            }
        ]
        projects = []
        phone = "+919876543210"
        email = "test@example.com"
        location = "Coimbatore"
        languages = ["English"]
        certifications = []
        companies = ["Cloud Destinations"]
        designation = "Software Engineer"

    normalized = ResumeNormalizer().normalize(DummyExtracted())
    assert len(normalized["experience"]) == 1
    norm_exp = normalized["experience"][0]
    assert norm_exp["company"] == "Cloud Destinations"
    assert norm_exp["job_title"] == "Software Engineer"
    assert norm_exp["employment_type"] == "Full-time"
    assert norm_exp["is_current"] is True
    assert norm_exp["description"] == "Bullet 1. Bullet 2. Bullet 3."
    assert norm_exp["responsibilities"] == ["Bullet 1", "Bullet 2", "Bullet 3"]
    assert norm_exp["location"] == "Coimbatore"


def test_12_company_title_dates_never_shift() -> None:
    text = """WORK EXPERIENCE
Innovate Tech, Bengaluru
Backend Developer
2022 – Present
- Developed REST API microservices using Python and FastAPI.
"""
    result = ResumeExtractor()._experience(text)
    assert len(result) == 1
    exp = result[0]
    # Company is not title
    assert exp["company"] == "Innovate Tech"
    assert exp["company"] != "Backend Developer"
    # Title is not company
    assert exp["title"] == "Backend Developer"
    assert exp["title"] != "Innovate Tech"
    # Dates are not company/title
    assert exp["company"] != "2022 – Present"
    assert exp["title"] != "2022 – Present"
    assert exp["is_current"] is True
