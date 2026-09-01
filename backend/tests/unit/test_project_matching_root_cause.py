import pytest
from app.services.extractors.resume_extractor import ResumeExtractor
from app.services.normalizers.resume_normalizer import ResumeNormalizer
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService
from types import SimpleNamespace


def test_scenario_a_explicit_projects_matching():
    raw_resume = """
    John Doe
    john@example.com
    +1 555-0199
    
    EXPERIENCE
    Software Engineer | ABC Corp | 2021 - 2023
    - Built internal services.
    
    PROJECTS
    E-Commerce Platform
    - Developed product listing, shopping cart, and order management using React, Node.js, and MongoDB.
    """
    extractor = ResumeExtractor()
    extracted_dict = extractor.extract(raw_resume)
    extracted = SimpleNamespace(**extracted_dict)
    assert len(extracted.projects) == 1
    assert "E-Commerce Platform" in extracted.projects[0]["name"]

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(extracted)
    assert "projects" in normalized
    assert len(normalized["projects"]) == 1

    job = SimpleNamespace(
        keywords=["E-Commerce", "React", "Node.js", "MongoDB", "Cart"],
        required_skills=["React", "Node.js", "MongoDB"],
        skills=["React", "Node.js", "MongoDB"],
        degree_requirements=[],
        responsibilities=[],
    )
    scorer = ComponentScoringService()
    proj_score = scorer._projects_score(extracted.projects, job)
    assert proj_score.score > 0.0
    assert "React" in proj_score.matched_items or "Node.js" in proj_score.matched_items


def test_scenario_b_embedded_projects_in_experience_matching():
    raw_resume = """
    Jane Smith
    jane@example.com
    +1 555-0200
    
    EXPERIENCE
    Senior Software Engineer | TechNova Solutions | 2022 - Present
    Project: Online Shopping Portal
    - Implemented product catalog, cart checkout, and order management using React, Node.js, and MongoDB.
    - Integrated Stripe payment gateway and microservices.
    """
    extractor = ResumeExtractor()
    extracted_dict = extractor.extract(raw_resume)
    extracted = SimpleNamespace(**extracted_dict)
    assert len(extracted.projects) == 1
    assert "Online Shopping Portal" in extracted.projects[0]["name"]

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(extracted)
    assert "projects" in normalized
    assert len(normalized["projects"]) == 1

    job = SimpleNamespace(
        keywords=["React", "Node.js", "MongoDB", "Cart"],
        required_skills=["React", "Node.js", "MongoDB"],
        skills=["React", "Node.js", "MongoDB"],
        degree_requirements=[],
        responsibilities=[],
    )
    scorer = ComponentScoringService()
    proj_score = scorer._projects_score(extracted.projects, job)
    assert proj_score.score > 0.0
    assert proj_score.score == 100.0


def test_scenario_c_generic_experience_does_not_inflate_projects():
    raw_resume = """
    Bob Taylor
    bob@example.com
    +1 555-0201
    
    EXPERIENCE
    Software Engineer | Legacy Systems Corp | 2020 - 2023
    - Built REST APIs and fixed production issues.
    - Worked on bug triage and system maintenance.
    """
    extractor = ResumeExtractor()
    extracted_dict = extractor.extract(raw_resume)
    extracted = SimpleNamespace(**extracted_dict)
    assert len(extracted.projects) == 0

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(extracted)
    assert normalized["projects"] == []

    job = SimpleNamespace(
        keywords=["E-Commerce", "React", "Node.js", "MongoDB"],
        required_skills=["React", "Node.js", "MongoDB"],
        skills=["React", "Node.js", "MongoDB"],
        degree_requirements=[],
        responsibilities=[],
    )
    scorer = ComponentScoringService()
    proj_score = scorer._projects_score(extracted.projects, job)
    assert proj_score.score == 0.0
    assert proj_score.matched_items == []
