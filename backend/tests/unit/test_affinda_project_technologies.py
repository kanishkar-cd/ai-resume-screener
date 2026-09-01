import pytest
from app.services.affinda_mapper import map_affinda_resume, _normalize_technology_entries


def test_normalize_technology_entries_string():
    raw = "Python, FastAPI, PostgreSQL"
    assert _normalize_technology_entries(raw) == ["Python", "FastAPI", "PostgreSQL"]


def test_normalize_technology_entries_semicolon_pipe_slash():
    assert _normalize_technology_entries("Python; FastAPI; PostgreSQL") == ["Python", "FastAPI", "PostgreSQL"]
    assert _normalize_technology_entries("Python | FastAPI | PostgreSQL") == ["Python", "FastAPI", "PostgreSQL"]
    assert _normalize_technology_entries("Python / FastAPI / PostgreSQL") == ["Python", "FastAPI", "PostgreSQL"]


def test_normalize_technology_entries_list_of_strings():
    raw = ["Python", "FastAPI", "PostgreSQL"]
    assert _normalize_technology_entries(raw) == ["Python", "FastAPI", "PostgreSQL"]


def test_normalize_technology_entries_list_of_objects():
    raw = [{"name": "Python"}, {"name": "FastAPI"}]
    res = _normalize_technology_entries(raw)
    assert res == [{"name": "Python"}, {"name": "FastAPI"}]


def test_normalize_technology_entries_empty():
    assert _normalize_technology_entries(None) == []
    assert _normalize_technology_entries([]) == []
    assert _normalize_technology_entries(123) == []


def test_affinda_mapper_string_technologies_does_not_split_into_characters():
    payload = {
        "candidateName": {"firstName": "Jane", "familyName": "Doe"},
        "project": [
            {
                "projectTitle": "E-Commerce App",
                "projectDescription": "Built web app with Python and FastAPI",
                "technologies": "Python, FastAPI, PostgreSQL",
            }
        ],
    }

    extracted, _ = map_affinda_resume(payload, "test-provider-id")
    projects = extracted.get("projects", [])
    assert len(projects) == 1
    techs = projects[0].get("technologies", [])
    assert techs == ["Python", "FastAPI", "PostgreSQL"]
    assert "P" not in techs
    assert "y" not in techs
    assert "t" not in techs


def test_affinda_mapper_list_technologies():
    payload = {
        "candidateName": {"firstName": "Jane", "familyName": "Doe"},
        "project": [
            {
                "projectTitle": "E-Commerce App",
                "projectDescription": "Built web app",
                "technologies": ["Python", "FastAPI", "PostgreSQL"],
            }
        ],
    }

    extracted, _ = map_affinda_resume(payload, "test-provider-id")
    projects = extracted.get("projects", [])
    assert len(projects) == 1
    assert projects[0].get("technologies") == ["Python", "FastAPI", "PostgreSQL"]


def test_affinda_mapper_object_technologies():
    payload = {
        "candidateName": {"firstName": "Jane", "familyName": "Doe"},
        "project": [
            {
                "projectTitle": "E-Commerce App",
                "projectDescription": "Built web app",
                "technologies": [{"name": "Python"}, {"name": "FastAPI"}],
            }
        ],
    }

    extracted, _ = map_affinda_resume(payload, "test-provider-id")
    projects = extracted.get("projects", [])
    assert len(projects) == 1
    assert projects[0].get("technologies") == ["Python", "FastAPI"]


def test_affinda_mapper_empty_technologies():
    payload = {
        "candidateName": {"firstName": "Jane", "familyName": "Doe"},
        "project": [
            {
                "projectTitle": "E-Commerce App",
                "projectDescription": "Built web app",
                "technologies": None,
            }
        ],
    }

    extracted, _ = map_affinda_resume(payload, "test-provider-id")
    projects = extracted.get("projects", [])
    assert len(projects) == 1
    assert projects[0].get("technologies") == []
