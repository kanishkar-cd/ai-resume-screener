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
Customer Centria, Coimbatore
Role : Database Management Intern
Three Months Internship
08/2025 – 10/2025
- Managed cloud databases and SQL querying.

PROJECTS
Project: Event Registering Portal (AWS Cloud)
- Built serverless web app using Lambda, API Gateway, S3, and DynamoDB.
Project: Devops-Based Ecommerce Website
- Deployed microservices using Docker, Jenkins, and Terraform.

CERTIFICATIONS
MongoDB
Azure DP-900
Overview Of Geographical
Information System (IIRS)
AWS Academy Cloud Foundations
Hackathon (Techgium)

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
    exp = result["experience"][0]
    assert exp["company"] == "Customer Centria"
    assert exp["designation"] == "Database Management Intern"
    assert exp["employment_type"] == "Internship"
    assert exp["start_date"] == "08/2025"
    assert exp["end_date"] == "10/2025"

    # Companies
    assert "Customer Centria" in result["companies"]

    # Designation
    assert result["designation"] == "Database Management Intern"

    # Projects (Must produce exactly 2 distinct project objects)
    assert len(result["projects"]) == 2
    assert "Event Registering Portal" in result["projects"][0]["name"]
    assert "Lambda" in result["projects"][0]["technologies"]
    assert "Devops-Based Ecommerce Website" in result["projects"][1]["name"]
    assert "Docker" in result["projects"][1]["technologies"]

    # Certifications (Must group wrapped lines and exclude non-certs)
    assert "MongoDB" in result["certifications"]
    assert "Azure DP-900" in result["certifications"]
    assert "Overview Of Geographical Information System (IIRS)" in result["certifications"]
    assert "AWS Academy Cloud Foundations" in result["certifications"]
    assert "Hackathon (Techgium)" in result["certifications"]

    # Quality & Confidence
    assert result["confidence_scores"]["email"] >= 0.95
    assert result["confidence_scores"]["phone"] >= 0.95
    assert result["confidence_scores"]["experience"] > 0
    assert result["confidence_scores"]["companies"] > 0
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


# ------------------------------------------------------------------ #
# Regression tests — Stage 3 extraction quality improvements
# ------------------------------------------------------------------ #

def test_project_splitting_into_two_distinct_objects() -> None:
    """Projects must split on each 'Project:' heading — never merge into one."""
    text = """Resume
PROJECTS
Project: Event Registering Portal (AWS Cloud)
- Built serverless web app using Lambda, API Gateway, S3, and DynamoDB.
Project: Devops-Based Ecommerce Website
- Deployed microservices using Docker, Jenkins, Terraform, EC2.
- Implemented CI/CD pipelines.
"""
    result = ResumeExtractor().extract(text)
    projects = result["projects"]
    names = [p["name"] for p in projects]
    assert len(projects) == 2, f"Expected 2 projects, got {len(projects)}: {names}"
    assert any("Event Registering Portal" in n for n in names), f"Missing Event Registering Portal: {names}"
    assert any("Devops-Based Ecommerce Website" in n for n in names), f"Missing Devops-Based Ecommerce Website: {names}"


def test_project_technologies_are_isolated_per_project() -> None:
    """Technologies must belong only to their respective project, not bleed across."""
    text = """PROJECTS
Project: Event Registering Portal (AWS Cloud)
- Built serverless web app using Lambda, API Gateway, S3, and DynamoDB.
Project: Devops-Based Ecommerce Website
- Deployed microservices using Docker, Jenkins, Terraform, EC2.
- Implemented CI/CD pipelines.
"""
    result = ResumeExtractor().extract(text)
    assert len(result["projects"]) == 2

    proj1 = result["projects"][0]  # Event Registering Portal
    proj2 = result["projects"][1]  # Devops-Based Ecommerce Website

    # Project 1 techs must include Lambda, S3, DynamoDB — NOT Docker or Jenkins
    for tech in ("Lambda", "S3"):
        assert tech in proj1["technologies"], f"{tech} missing from Project 1 techs: {proj1['technologies']}"
    assert "Docker" not in proj1["technologies"], "Docker bled into Project 1"
    assert "Jenkins" not in proj1["technologies"], "Jenkins bled into Project 1"

    # Project 2 techs must include Docker, Jenkins, Terraform — NOT Lambda or S3
    for tech in ("Docker", "Jenkins", "Terraform"):
        assert tech in proj2["technologies"], f"{tech} missing from Project 2 techs: {proj2['technologies']}"
    assert "Lambda" not in proj2["technologies"], "Lambda bled into Project 2"


def test_multiline_certification_merging() -> None:
    """Multi-line certifications must be merged into single entries."""
    text = """CERTIFICATIONS
MongoDB
Azure DP-900
Overview Of Geographical
Information System (IIRS)
AWS Academy Cloud Foundations
Hackathon (Techgium)
"""
    result = ResumeExtractor().extract(text)
    certs = result["certifications"]
    assert "MongoDB" in certs
    assert "Azure DP-900" in certs
    assert any("Overview Of Geographical Information System" in c for c in certs), \
        f"Wrapped IIRS cert not merged. Got: {certs}"
    assert "AWS Academy Cloud Foundations" in certs
    assert "Hackathon (Techgium)" in certs


def test_ocr_cert_garbage_removal() -> None:
    """OCR artefacts must be cleaned: badge counts, DP900 variants, missing parens space."""
    text = """CERTIFICATIONS
MongoDB
Azure DP900-8 badges,3
Overview Of Geographical
Information System(IIRS)
AWS Academy Graduate-
Cloud Foundations - Training
Hackathon (Techgium)
"""
    result = ResumeExtractor().extract(text)
    certs = result["certifications"]

    # Must not contain raw OCR garbage
    for c in certs:
        assert "badges" not in c.lower(), f"'badges' OCR noise not removed: {c!r}"
        assert c.lower() != "badge", f"Standalone 'Badge' OCR noise not removed: {c!r}"
        assert "DP900-8" not in c, f"DP900-8 OCR noise not normalized: {c!r}"
        assert "Graduate-" not in c, f"'Graduate-' not cleaned: {c!r}"
        assert "- Training" not in c, f"'- Training' suffix not removed: {c!r}"

    # Must contain cleaned versions
    assert any("DP-900" in c for c in certs), f"DP-900 not found in: {certs}"
    assert any("AWS Academy Cloud Foundations" in c for c in certs), \
        f"AWS Academy Cloud Foundations not in: {certs}"
    assert any("Overview Of Geographical Information System" in c for c in certs), \
        f"IIRS cert not merged: {certs}"
    assert "Hackathon (Techgium)" in certs, f"Hackathon missing from: {certs}"


def test_internship_date_extraction() -> None:
    """Experience must extract start_date and end_date from date ranges in the resume while preserving text duration."""
    text = """INTERSHIP
Customer Centria, Coimbatore
Role : Database Management Intern
Three Months Internship
08/2025 - 10/2025
- Managed cloud databases and SQL querying.
"""
    result = ResumeExtractor().extract(text)
    assert len(result["experience"]) >= 1
    exp = result["experience"][0]
    assert exp.get("start_date") == "08/2025", f"start_date wrong: {exp.get('start_date')!r}"
    assert exp.get("end_date") == "10/2025", f"end_date wrong: {exp.get('end_date')!r}"
    assert "Three Months" in (exp.get("duration") or ""), f"duration text preserved: {exp.get('duration')!r}"
    assert exp.get("company") == "Customer Centria"
    assert exp.get("employment_type") == "Internship"


def test_ocr_location_fragment_not_in_description() -> None:
    """Isolated city fragments like 'Coimba' must not appear in experience description."""
    text = """INTERSHIP
Customer Centria, Coimbatore
Role : Database Management Intern
08/2025 - 10/2025
Coimba
- Managed cloud databases and SQL querying.
"""
    result = ResumeExtractor().extract(text)
    assert len(result["experience"]) >= 1
    exp = result["experience"][0]
    desc = exp.get("description") or ""
    responsibilities = exp.get("responsibilities") or []
    assert "Coimba" not in desc, f"OCR city fragment 'Coimba' leaked into description: {desc!r}"
    assert not any("Coimba" in r for r in responsibilities), \
        f"OCR city fragment in responsibilities: {responsibilities}"
    # Real content must still be present
    assert "Managed cloud databases" in desc, f"Real description missing: {desc!r}"


def test_section_heading_not_stolen_by_content_line_training() -> None:
    """'Cloud Foundations - Training' must NOT be treated as a section heading."""
    from app.services.pipeline.extraction_pipeline import segment_sections
    text = """CERTIFICATIONS
MongoDB
Azure DP-900
AWS Academy Graduate-
Cloud Foundations - Training
Hackathon (Techgium)
"""
    sections = segment_sections(text)
    # All cert lines must stay inside certifications, not escape into a spurious 'trainings' section
    assert "trainings" not in sections, \
        f"'trainings' section created from certification content: {list(sections.keys())}"
    cert_block = sections.get("certifications", "")
    assert "Hackathon" in cert_block, \
        f"Hackathon was stolen from certifications block. Sections: {list(sections.keys())}"


def test_real_ocr_resume_full_extraction() -> None:
    """Full extraction against the real OCR artefact text must meet all acceptance criteria."""
    text = """Shri Harini Karthika
sasikumar80989705@gmail.com
9043652396
Coimbatore

EDUCATION
Bachelor of Technology in Artificial Intelligence and Data Science
Rathinam Technical Campus
9.0 CGPA

INTERSHIP
Customer Centria, Coimbatore
Role : Database Management Intern
Three Months Internship
08/2025 - 10/2025
Coimba
- Managed cloud databases and SQL querying.

PROJECTS
Project: Event Registering Portal (AWS Cloud)
- Built serverless web app using Lambda, API Gateway, S3, and DynamoDB.
Project: Devops-Based Ecommerce Website
- Deployed microservices using Docker, Jenkins, Terraform, EC2.
- Implemented CI/CD pipelines.

CERTIFICATIONS
MongoDB
Azure DP900-8 badges,3
Overview Of Geographical
Information System(IIRS)
AWS Academy Graduate-
Cloud Foundations - Training
Hackathon (Techgium)

TECHNICAL SKILLS
Python, SQL, AWS, Lambda, API Gateway, S3, DynamoDB, Docker, Jenkins, Terraform
"""
    result = ResumeExtractor().extract(text)

    # Basic identity
    assert result["candidate_name"] == "Shri Harini Karthika"
    assert result["email"] == "sasikumar80989705@gmail.com"

    # Experience
    assert len(result["experience"]) >= 1
    exp = result["experience"][0]
    assert exp["company"] == "Customer Centria"
    assert exp["employment_type"] == "Internship"
    assert exp["start_date"] == "08/2025"
    assert exp["end_date"] == "10/2025"
    assert "Coimba" not in (exp.get("description") or "")

    # Companies
    assert "Customer Centria" in result["companies"]

    # Projects — exactly 2 distinct objects
    assert len(result["projects"]) == 2
    names = [p["name"] for p in result["projects"]]
    assert any("Event Registering Portal" in n for n in names)
    assert any("Devops-Based Ecommerce Website" in n for n in names)

    # Certifications — cleaned and complete
    certs = result["certifications"]
    assert "MongoDB" in certs
    assert any("DP-900" in c for c in certs)
    assert any("Overview Of Geographical Information System" in c for c in certs)
    assert any("AWS Academy Cloud Foundations" in c for c in certs)
    assert "Hackathon (Techgium)" in certs
    assert all("badges" not in c.lower() for c in certs)

    # Confidence
    assert result["confidence_scores"]["experience"] > 0
    assert result["confidence_scores"]["companies"] > 0
    assert result["confidence_scores"]["certifications"] > 0


def test_stage3_final_polish_validation() -> None:
    """Comprehensive regression test validating:
    - 2 projects with isolated technologies
    - 1 experience with company & designation extracted
    - start_date and end_date populated
    - duration preserved
    - certifications cleaned with no OCR artifacts
    """
    text = """Shri Harini Karthika
sasikumar80989705@gmail.com
9043652396
Coimbatore

EDUCATION
Bachelor of Technology in Artificial Intelligence and Data Science
Rathinam Technical Campus
9.0 CGPA

INTERSHIP
Customer Centria, Coimbatore
Role : Database Management Intern
Three Months Internship
08/2025 - 10/2025
Coimba
- Managed cloud databases and SQL querying.

PROJECTS
Project: Event Registering Portal (AWS Cloud)
- Built serverless web app using Lambda, API Gateway, S3, and DynamoDB.
Project: Devops-Based Ecommerce Website
- Deployed microservices using Docker, Jenkins, Terraform, EC2.
- Implemented CI/CD pipelines.

CERTIFICATIONS
MongoDB
Azure DP900-8 badges,3
Badge
Overview Of Geographical
Information System(IIRS)
AWS Academy Graduate-
Cloud Foundations - Training
Hackathon (Techgium)
"""
    result = ResumeExtractor().extract(text)

    # 1. Projects validation
    assert len(result["projects"]) == 2, f"Expected 2 projects, got {len(result['projects'])}"
    p1, p2 = result["projects"][0], result["projects"][1]
    assert "Event Registering Portal" in p1["name"]
    assert "Devops-Based Ecommerce Website" in p2["name"]

    # Technology isolation validation
    assert "Lambda" in p1["technologies"] and "S3" in p1["technologies"]
    assert "Docker" not in p1["technologies"]
    assert "Docker" in p2["technologies"] and "Jenkins" in p2["technologies"]
    assert "Lambda" not in p2["technologies"]

    # 2. Experience validation
    assert len(result["experience"]) == 1, f"Expected 1 experience entry, got {len(result['experience'])}"
    exp = result["experience"][0]
    assert exp["company"] == "Customer Centria"
    assert exp["designation"] == "Database Management Intern"
    assert exp["employment_type"] == "Internship"
    assert exp["start_date"] == "08/2025"
    assert exp["end_date"] == "10/2025"
    assert "Three Months" in (exp.get("duration") or "")

    # 3. Certifications validation
    certs = result["certifications"]
    assert "MongoDB" in certs
    assert "Azure DP-900" in certs
    assert "AWS Academy Cloud Foundations" in certs
    assert "Hackathon (Techgium)" in certs
    assert any("Overview Of Geographical Information System" in c for c in certs)

    # OCR artifacts check
    assert not any(c.lower() == "badge" for c in certs)
    assert not any("badges" in c.lower() for c in certs)
    assert not any("Coimba" in (exp.get("description") or "") for exp in result["experience"])

