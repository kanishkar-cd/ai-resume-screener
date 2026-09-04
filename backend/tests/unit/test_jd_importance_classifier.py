import pytest
from unittest.mock import AsyncMock, patch

from app.schemas.matching import RequirementKind
from app.services.extractors.jd_importance_classifier import (
    JDRequirementImportanceClassifier,
    RequirementClassification,
)
from app.services.matching_service import RequirementBuilder


@pytest.mark.asyncio
async def test_jd_importance_classifier_heuristic_fallback():
    classifier = JDRequirementImportanceClassifier()
    jd_text = """
    Senior Python Engineer
    Requirements:
    - 5+ years of Python
    - FastAPI and PostgreSQL experience
    - Excellent communication skills and team player
    """
    reqs = ["Python", "FastAPI", "PostgreSQL", "Excellent communication skills and team player"]

    # Test heuristic fallback (no API keys provided or offline)
    with patch.object(classifier, "settings") as mock_settings:
        mock_settings.GROQ_API_KEY = None
        mock_settings.CEREBRAS_API_KEY = None
        results = await classifier.classify(jd_text, reqs)

    assert len(results) == 4
    comm_key = "excellent communication skills and team player".casefold()
    assert comm_key in results
    assert results[comm_key].importance == "minor"
    assert results[comm_key].is_likely_boilerplate is True

    py_key = "python".casefold()
    assert py_key in results
    assert results[py_key].importance == "important"
    assert results[py_key].is_likely_boilerplate is False


@pytest.mark.asyncio
async def test_requirement_builder_with_classifications():
    class DummyJob:
        skills = ["Python", "Excellent communication skills"]
        responsibilities = ["Design scalable REST APIs"]
        preferred_skills = ["Docker"]
        degree_requirements = []
        experience_requirements = []
        certifications = []
        project_requirements = []

    classifications = {
        "python": RequirementClassification(
            requirement_text="Python",
            importance="critical",
            reasoning="Listed under essential core requirements.",
            is_likely_boilerplate=False,
        ),
        "excellent communication skills": RequirementClassification(
            requirement_text="Excellent communication skills",
            importance="minor",
            reasoning="Generic boilerplate item.",
            is_likely_boilerplate=True,
        ),
        "design scalable rest apis": RequirementClassification(
            requirement_text="Design scalable REST APIs",
            importance="critical",
            reasoning="Core engineering responsibility.",
            is_likely_boilerplate=False,
        ),
    }

    built = RequirementBuilder.build(DummyJob(), config=None, classifications=classifications)
    req_map = {r.text: r for r in built}

    assert "Python" in req_map
    assert req_map["Python"].importance == "critical"
    assert req_map["Python"].is_likely_boilerplate is False
    assert "essential core requirements" in (req_map["Python"].importance_reasoning or "")

    assert "Excellent communication skills" in req_map
    assert req_map["Excellent communication skills"].importance == "minor"
    assert req_map["Excellent communication skills"].is_likely_boilerplate is True

    assert "Design scalable REST APIs" in req_map
    assert req_map["Design scalable REST APIs"].importance == "critical"
    assert req_map["Design scalable REST APIs"].kind == RequirementKind.RESPONSIBILITY
