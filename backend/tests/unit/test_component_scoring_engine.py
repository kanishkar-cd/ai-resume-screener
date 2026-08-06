from types import SimpleNamespace

from app.schemas.scoring import ComponentScores
from app.services.scoring.component_scoring_service import ComponentScoringService


def test_component_engine_formulas_and_boundaries() -> None:
    resume = SimpleNamespace(
        skills=["Python", "Docker"], experience=[{"duration_months": 36}],
        education=[{"degree": "Master of Science"}], certifications=["AWS"], languages=["English"],
    )
    job = SimpleNamespace(
        skills=["Python", "PostgreSQL"], experience_requirements=[{"minimum_months": 48}],
        degree_requirements=["Bachelor of Engineering"], keywords=["Docker"],
    )
    config = SimpleNamespace(mandatory_skills=[], min_experience_years=3, required_degree=None, required_certifications=["AWS"])
    scores = ComponentScoringService().score(resume, job, config, [{"technologies": ["Docker"], "name": "Platform"}])
    assert scores.skills.score == 50 and scores.skills.missing_items == ["PostgreSQL"]
    assert scores.experience.score == 75
    assert scores.education.score == 100
    assert scores.projects.score == 100
    assert scores.certifications.score == 100
    assert scores.languages.score == 100


def test_no_requirement_component_scores_one_hundred() -> None:
    resume = SimpleNamespace(skills=[], experience=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    config = SimpleNamespace(mandatory_skills=[], min_experience_years=0, required_degree=None, required_certifications=[])
    scores = ComponentScoringService().score(resume, job, config)
    assert all(getattr(scores, name).score == 100 for name in ComponentScores.model_fields)
