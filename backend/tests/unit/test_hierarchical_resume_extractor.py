from app.services.extractors.resume_extractor import ResumeExtractor


def test_shri_harini_karthika_resume_sample_extraction() -> None:
    sample_text = """Shri Harini Karthika
sasikumar80989705@gmail.com
9043652396
Coimbatore

EDUCATION
Bachelor of Technology in Artificial Intelligence and Data Science
Rathinam Technical Campus
9.0 CGPA

INTERNSHIP
Customer Centria
Role : Database Management Intern
Three Months Internship
08/2025 – 10/2025
- Managed cloud databases and SQL querying.

PROJECTS
Project: Event Registering Portal (AWS Cloud)
- Built serverless web app using Lambda, API Gateway, S3, and DynamoDB.
Project: Devops-Based Ecommerce Website
- Deployed microservices using Docker, Jenkins, and Terraform.

TECHNICAL SKILLS
Python, SQL, AWS, Lambda, API Gateway, S3, DynamoDB, Docker, Jenkins, Terraform
"""
    result = ResumeExtractor().extract(sample_text)

    assert result["candidate_name"] == "Shri Harini Karthika"
    assert result["email"] == "sasikumar80989705@gmail.com"
    assert result["phone"] == "9043652396"
    assert "Coimbatore" in (result["location"] or "")

    # Education
    assert len(result["education"]) >= 1
    assert result["education"][0]["degree"] == "Bachelor of Technology"
    assert "Rathinam Technical Campus" in (result["education"][0]["institution"] or "")
    assert "9.0" in (result["education"][0]["grade"] or "")

    # Experience / Internship
    assert len(result["experience"]) >= 1
    assert "Customer Centria" in (result["experience"][0]["company"] or "")
    assert "Database Management Intern" in (result["experience"][0]["title"] or "")
    assert "08/2025" in (result["experience"][0]["duration"] or "")

    # Designation
    assert result["designation"] == "Database Management Intern"

    # Projects
    assert len(result["projects"]) == 2
    assert "Event Registering Portal" in result["projects"][0]["name"]
    assert "Lambda" in result["projects"][0]["technologies"]
    assert "Devops-Based Ecommerce Website" in result["projects"][1]["name"]
    assert "Docker" in result["projects"][1]["technologies"]

    # Quality & Confidence
    assert result["confidence_scores"]["email"] >= 0.95
    assert result["confidence_scores"]["phone"] >= 0.95
    assert result["raw_metadata"]["overall_quality_score"] >= 0.80


def test_fresher_resume_extraction() -> None:
    text = """Alex Smith
Alex.Smith2024@university.edu | +1 (555) 234-5678 | San Francisco, CA

OBJECTIVE
Motivated Computer Science graduate seeking Junior Software Engineer role.

EDUCATION
Bachelor of Science in Computer Science, Stanford University (2020 - 2024)
GPA: 3.9/4.0

TECHNICAL SKILLS
Python, Java, JavaScript, HTML, CSS, React, Git, SQL

PROJECTS
Smart Health Tracker:
- Built React frontend and Python FastAPI backend for real-time fitness metrics.
- Integrated SQLite database and Docker containerization.

INTERNSHIP
Software Developer Intern at Startup Hub | Summer 2023
- Implemented REST API endpoints in Python.

CERTIFICATIONS
Oracle Certified Associate Java SE (2023)

LANGUAGES
English
"""
    result = ResumeExtractor().extract(text)

    assert result["candidate_name"] == "Alex Smith"
    assert result["email"] == "Alex.Smith2024@university.edu"
    assert result["phone"] == "+1 (555) 234-5678"
    assert "San Francisco" in (result["location"] or "")
    assert result["education"][0]["degree"] == "Bachelor of Science"
    assert "3.9/4.0" in (result["education"][0]["grade"] or "")
    assert len(result["projects"]) == 1
    assert result["projects"][0]["name"] == "Smart Health Tracker"
    assert "Oracle Certified Associate Java SE (2023)" in result["certifications"]
    assert not any("Intern" in c for c in result["certifications"])


def test_experienced_candidate_multi_company_extraction() -> None:
    text = """Robert Johnson
robert.j@enterprise.org
+44 20 7946 0958
London, UK

SUMMARY
Principal DevOps & Cloud Solutions Architect with 10+ years experience.

WORK HISTORY
Principal DevOps Engineer at CloudTech Systems | 2021 - Present
- Managed AWS, Azure, GCP infrastructure with Terraform and Kubernetes.
- Set up GitLab CI/CD pipelines and Prometheus monitoring.

Senior Systems Architect - DataCorp Ltd | 2017 - 2021
- Designed distributed databases using PostgreSQL, MongoDB, and Redis.

TECHNICAL SKILLS
AWS, Azure, GCP, Terraform, Kubernetes, Docker, Python, Go, Linux, Jenkins, Ansible, Prometheus, Grafana

EDUCATION
Master of Science in Software Engineering, Imperial College London, 2016
"""
    result = ResumeExtractor().extract(text)

    assert result["candidate_name"] == "Robert Johnson"
    assert result["email"] == "robert.j@enterprise.org"
    assert result["phone"] == "+44 20 7946 0958"
    assert "London" in (result["location"] or "")
    assert len(result["experience"]) >= 2
    assert "CloudTech Systems" in (result["experience"][0]["company"] or "")
    assert "Terraform" in result["skills"]
    assert "Linux" in result["skills"]
    assert "Jenkins" in result["skills"]


def test_ocr_extracted_two_column_resume() -> None:
    text = """Priya Sharma
priya.sharma@techmail.com
Phone +91-9988776655
Location Bengaluru

SKILLS
Python FastAPI PostgreSQL MongoDB Docker HTML CSS Jenkins AWS

EXPERIENCE
Backend Developer at Innovate Tech | 2022 - Present
Developed REST API microservices using Python and FastAPI.

EDUCATION
B.Tech in Information Technology
National Institute of Technology
Year 2022 CGPA 8.8

PROJECTS
AI Resume Screener App
Created automated resume parsing engine with PyMuPDF and EasyOCR.
"""
    result = ResumeExtractor().extract(text)

    assert result["candidate_name"] == "Priya Sharma"
    assert result["email"] == "priya.sharma@techmail.com"
    assert result["phone"] == "+91-9988776655"
    assert "Bengaluru" in (result["location"] or "")
    assert result["education"][0]["degree"] == "Bachelor of Technology"
    assert "Innovate Tech" in (result["experience"][0]["company"] or "")
    assert result["projects"][0]["name"] == "AI Resume Screener App"
