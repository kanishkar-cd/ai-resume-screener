import pytest
from app.services.extractors.resume_extractor import ResumeExtractor
from app.services.affinda_mapper import _normalize_technology_entries, map_affinda_resume


def test_three_projects_in_continuous_single_line_text():
    raw_block = (
        "Project Alpha | Python, FastAPI • Developed high throughput REST endpoints with async background tasks. "
        "• Reduced query latency by 45% using Redis caching. "
        "Project Beta | React, TypeScript • Built interactive dashboards with real-time WebSocket state updates. "
        "• Implemented responsive UI with accessibility standards. "
        "Project Gamma | Docker, Kubernetes, AWS • Deployed microservices to EKS cluster with Istio ingress. "
        "• Automated CI/CD pipelines with GitHub Actions."
    )
    projects = ResumeExtractor._projects(raw_block)
    assert len(projects) == 3

    # Project Alpha
    assert projects[0]["name"] == "Project Alpha"
    assert "Redis" in projects[0]["description"] or "endpoints" in projects[0]["description"]
    assert "Python" in projects[0]["technologies"]
    assert "FastAPI" in projects[0]["technologies"]
    assert "React" not in projects[0]["technologies"]
    assert "Docker" not in projects[0]["technologies"]

    # Project Beta
    assert projects[1]["name"] == "Project Beta"
    assert "WebSocket" in projects[1]["description"] or "dashboards" in projects[1]["description"]
    assert "React" in projects[1]["technologies"]
    assert "TypeScript" in projects[1]["technologies"]
    assert "FastAPI" not in projects[1]["technologies"]

    # Project Gamma
    assert projects[2]["name"] == "Project Gamma"
    assert "EKS" in projects[2]["description"] or "microservices" in projects[2]["description"]
    assert "Docker" in projects[2]["technologies"]
    assert "Kubernetes" in projects[2]["technologies"]
    assert "Python" not in projects[2]["technologies"]


def test_two_projects_separated_by_inline_year_headings():
    raw_block = (
        "Article Scraper Tool 2026 Built a news scraping automation tool using Selenium and Python. "
        "Validated search and pagination components. "
        "Shopping Collaboration App 2025 Developed a collaborative web platform with authentication and Postman test suites."
    )
    projects = ResumeExtractor._projects(raw_block)
    assert len(projects) == 2
    assert projects[0]["name"] == "Article Scraper Tool"
    assert "Selenium" in projects[0]["technologies"] or "Python" in projects[0]["technologies"]
    assert projects[1]["name"] == "Shopping Collaboration App"
    assert "Postman" in projects[1]["technologies"] or "Postman" in projects[1]["description"]


def test_project_heading_containing_pipe_tech_stack_strips_title_cleanly():
    raw_block = (
        "Distributed Ledger Platform | Go, gRPC, PostgreSQL • Implemented consensus mechanism with fault tolerance. "
        "Analytics Dashboard System | Vue.js, Node.js • Visualized metrics and user event streams."
    )
    projects = ResumeExtractor._projects(raw_block)
    assert len(projects) == 2
    assert projects[0]["name"] == "Distributed Ledger Platform"
    assert projects[1]["name"] == "Analytics Dashboard System"
    assert "Go" in projects[0]["technologies"] or "PostgreSQL" in projects[0]["technologies"]
    assert "Vue.js" in projects[1]["technologies"] or "Node.js" in projects[1]["technologies"]


def test_project_descriptions_preserve_punctuation_and_symbols():
    raw_block = (
        "Data Pipeline Engine | Python, PySpark • Processed 100,000+ daily events; filtered nulls/duplicates. "
        "• Maintained 99.9% uptime (24/7 SLAs) with error-recovery & auto-retries."
    )
    projects = ResumeExtractor._projects(raw_block)
    assert len(projects) >= 1
    desc = projects[0]["description"]
    assert "100,000+" in desc
    assert "99.9%" in desc
    assert "error-recovery & auto-retries" in desc


def test_phase2_technology_normalization_regression():
    raw_tech = "Python, FastAPI, PostgreSQL"
    normalized = _normalize_technology_entries(raw_tech)
    assert normalized == ["Python", "FastAPI", "PostgreSQL"]


def test_multiline_standard_project_extraction():
    raw_block = (
        "Project: Smart City Traffic\n"
        "• Built an automated traffic monitoring service using Python and OpenCV.\n"
        "• Integrated YOLOv8 for real-time vehicle detection.\n"
        "Project: Cloud Storage Gateway\n"
        "• Implemented S3-compatible object store using Go and MinIO.\n"
        "• Enforced chunked multi-part uploads with checksum verification."
    )
    projects = ResumeExtractor._projects(raw_block)
    assert len(projects) == 2
    assert "Smart City Traffic" in projects[0]["name"]
    assert "Cloud Storage Gateway" in projects[1]["name"]


def test_single_named_project_with_multiple_bullets_does_not_split():
    raw_block = (
        "Project: Cloud Infrastructure Monitoring & Automation\n"
        "- Linux monitoring with CloudWatch: Configured alarms and metrics dashboard.\n"
        "- Database backup system: Wrote bash and python scripts for automated S3 backup.\n"
        "- API Gateway configuration: Enforced rate limiting and token authentication."
    )
    projects = ResumeExtractor._projects(raw_block)
    assert len(projects) == 1
    assert projects[0]["name"] == "Cloud Infrastructure Monitoring & Automation"
    assert "CloudWatch" in projects[0]["description"]
    assert "Database backup" in projects[0]["description"]
    assert "API Gateway" in projects[0]["description"]
    assert "Python" in projects[0]["technologies"] or "S3" in projects[0]["technologies"]


def test_single_named_project_with_dash_bullets_and_colons():
    raw_block = (
        "DevOps Automation Suite | AWS, Docker, Kubernetes\n"
        "- Task 1: Implemented Terraform infrastructure as code.\n"
        "- Task 2: Configured Helm charts and ArgoCD for GitOps deployments.\n"
        "- Task 3: Monitored system health with Datadog."
    )
    projects = ResumeExtractor._projects(raw_block)
    assert len(projects) == 1
    assert projects[0]["name"] == "DevOps Automation Suite"
    assert "Terraform" in projects[0]["description"]
    assert "ArgoCD" in projects[0]["description"]
    assert "Docker" in projects[0]["technologies"]

