import pytest
from app.services.extractors.resume_extractor import ResumeExtractor
from app.services.affinda_mapper import _map_projects, _normalize_technology_entries, map_affinda_resume
from app.services.normalizers.resume_normalizer import ResumeNormalizer


def test_1_three_projects_with_separate_descriptions():
    block = (
        "Project Alpha | Python\n"
        "• Description for Alpha only.\n"
        "Project Beta | React\n"
        "• Description for Beta only.\n"
        "Project Gamma | Go\n"
        "• Description for Gamma only."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 3
    assert "Alpha only" in projects[0]["description"]
    assert "Beta only" not in projects[0]["description"]
    assert "Beta only" in projects[1]["description"]
    assert "Gamma only" not in projects[1]["description"]
    assert "Gamma only" in projects[2]["description"]


def test_2_three_projects_with_different_technology_stacks():
    block = (
        "Project Alpha | Python, FastAPI\n"
        "• Created microservices.\n"
        "Project Beta | React, TypeScript\n"
        "• Created UI frontend.\n"
        "Project Gamma | Docker, Kubernetes\n"
        "• Managed infrastructure."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 3
    assert set(projects[0]["technologies"]) == {"Python", "FastAPI"}
    assert set(projects[1]["technologies"]) == {"React", "TypeScript"}
    assert set(projects[2]["technologies"]) == {"Docker", "Kubernetes"}


def test_3_continuous_single_line_project_text():
    block = (
        "Retail Data Pipeline | Python, PySpark • Processed retail streams. "
        "Airflow ETL System | Apache Airflow, Docker • Scheduled workflows. "
        "Analytics Dashboard | PostgreSQL, SQL • Built reporting tables."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 3
    assert projects[0]["name"] == "Retail Data Pipeline"
    assert projects[1]["name"] == "Airflow ETL System"
    assert projects[2]["name"] == "Analytics Dashboard"


def test_4_pipe_separated_technology_stack():
    block = "Distributed DB | Rust, RocksDB, gRPC • Built consensus layer."
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 1
    assert projects[0]["name"] == "Distributed DB"
    assert "Rust" in projects[0]["technologies"]


def test_5_year_separated_projects():
    block = (
        "Search Engine 2026 Designed search index with elasticsearch. "
        "Payment Gateway 2025 Integrated stripe webhook processing."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 2
    assert projects[0]["name"] == "Search Engine"
    assert projects[1]["name"] == "Payment Gateway"


def test_6_bullet_descriptions():
    block = (
        "• Project: E-Commerce Platform\n"
        "  • Built shopping cart module.\n"
        "  • Integrated Stripe checkout.\n"
        "• Project: Order Dispatch System\n"
        "  • Handled inventory allocation."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 2
    assert "shopping cart" in projects[0]["description"]
    assert "inventory allocation" in projects[1]["description"]


def test_7_technologies_mentioned_inside_descriptions():
    block = (
        "Customer Analytics Service\n"
        "Engineered transactional tables using PostgreSQL and optimized queries with Redis caching."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 1
    assert "PostgreSQL" in projects[0]["technologies"]
    assert "Redis" in projects[0]["technologies"]


def test_8_explicit_technologies_label():
    block = (
        "Project Delta\n"
        "Technologies: Python, Django, Celery\n"
        "• Implemented asynchronous task queue."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 1
    assert projects[0]["name"] == "Project Delta"
    assert "Python" in projects[0]["technologies"]
    assert "Django" in projects[0]["technologies"]
    assert "Celery" in projects[0]["technologies"]


def test_9_duplicate_technology_names_case_insensitive():
    block = "Project Epsilon | Python, python, PYTHON, React, react • Developed fullstack app."
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 1
    techs = projects[0]["technologies"]
    # Casefold duplicates should be stripped
    assert len([t for t in techs if t.casefold() == "python"]) == 1
    assert len([t for t in techs if t.casefold() == "react"]) == 1


def test_10_missing_description():
    block = "Project Minimal | Python, FastAPI"
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 1
    assert projects[0]["name"] == "Project Minimal"
    assert "Python" in projects[0]["technologies"]


def test_11_missing_technology_list():
    block = (
        "Academic Research Project\n"
        "Conducted empirical evaluation of distributed consensus protocols."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 1
    assert "Academic Research Project" in projects[0]["name"]
    assert "empirical evaluation" in projects[0]["description"]


def test_12_affinda_empty_description_fallback_valid_description():
    affinda_items = [{"projectTitle": "Custom Tool", "projectDescription": None, "technologies": ["Python"]}]
    source_text = "PROJECTS Custom Tool | Python • Built automated linting and formatting tool."
    mapped = _map_projects(affinda_items, source_text)
    assert len(mapped) == 1
    assert mapped[0]["name"] == "Custom Tool"
    assert "automated linting" in (mapped[0].get("description") or "")


def test_13_affinda_empty_title_fallback_valid_title():
    affinda_items = [{"projectTitle": None, "projectDescription": None, "technologies": []}]
    source_text = "PROJECTS Smart City Traffic | Python • Automated traffic camera recognition."
    mapped = _map_projects(affinda_items, source_text)
    assert len(mapped) == 1
    assert mapped[0]["name"] == "Smart City Traffic"
    assert "traffic camera" in mapped[0]["description"]


def test_14_project_a_must_not_contain_project_b_description():
    block = (
        "Project A | Python • Built backend service. "
        "Project B | React • Built frontend portal."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 2
    assert "frontend portal" not in projects[0]["description"]
    assert "backend service" not in projects[1]["description"]


def test_15_project_a_must_not_contain_project_b_technologies():
    block = (
        "Project A | Python, Flask • Implemented REST endpoints. "
        "Project B | Rust, WebAssembly • Created client engine."
    )
    projects = ResumeExtractor._projects(block)
    assert len(projects) == 2
    assert "Rust" not in projects[0]["technologies"]
    assert "WebAssembly" not in projects[0]["technologies"]
    assert "Python" not in projects[1]["technologies"]
    assert "Flask" not in projects[1]["technologies"]


def test_16_global_resume_skills_not_copied_into_projects():
    # End-to-end mapper test with global resume skills
    payload = {
        "candidateName": {"raw": "Test Candidate"},
        "skills": [{"name": "C++"}, {"name": "Java"}, {"name": "Kubernetes"}, {"name": "Python"}],
        "project": [
            {
                "projectTitle": "Frontend App",
                "projectDescription": "Built UI components",
                "technologies": [{"name": "React"}]
            }
        ]
    }
    extracted, normalized = map_affinda_resume(payload, "prov-1", "Source text with React and C++")
    proj = extracted["projects"][0]
    assert proj["technologies"] == ["React"]
    assert "C++" not in proj["technologies"]
    assert "Java" not in proj["technologies"]


def test_17_phase1_regression_three_continuous_projects():
    raw_block = (
        "Project Alpha | Python, FastAPI • Developed endpoints. "
        "Project Beta | React, TypeScript • Built dashboards. "
        "Project Gamma | Docker, Kubernetes • Deployed containers."
    )
    projects = ResumeExtractor._projects(raw_block)
    assert len(projects) == 3
    assert projects[0]["name"] == "Project Alpha"
    assert projects[1]["name"] == "Project Beta"
    assert projects[2]["name"] == "Project Gamma"


def test_18_phase2_technology_normalization_regression():
    raw_tech = "Python, FastAPI, PostgreSQL"
    normalized = _normalize_technology_entries(raw_tech)
    assert normalized == ["Python", "FastAPI", "PostgreSQL"]
