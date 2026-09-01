import pytest
from types import SimpleNamespace
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService


def test_1_standalone_project():
    job = SimpleNamespace(
        keywords=["E-Commerce", "React", "Node.js", "MongoDB"],
        required_skills=["React", "Node.js"],
        skills=["React", "Node.js"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["React", "Node.js"],
        projects=[{
            "name": "E-Commerce Store",
            "description": "Online shopping store with product catalog and cart.",
            "technologies": ["React", "Node.js", "MongoDB"],
        }],
        experience=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None, projects=resume.projects)
    assert scores.projects.score > 0.0
    assert "React" in scores.projects.matched_items or "Node.js" in scores.projects.matched_items


def test_2_experienced_candidate_with_implementation_evidence():
    job = SimpleNamespace(
        keywords=["E-Commerce", "React", "Node.js", "MongoDB"],
        required_skills=["React", "Node.js"],
        skills=["React", "Node.js"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["React", "Node.js", "MongoDB"],
        projects=[],  # No standalone projects section
        experience=[{
            "company": "Tech Corp",
            "title": "Software Engineer",
            "description": "Built an e-commerce platform using React and Node.js. Developed product listing and cart.",
            "responsibilities": ["Implemented MongoDB schemas and REST APIs."],
            "technologies": ["React", "Node.js", "MongoDB"],
            "duration_months": 36,
        }],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.projects.score > 0.0
    assert "React" in scores.projects.matched_items or "Node.js" in scores.projects.matched_items


def test_3_no_project_requirement_is_na():
    job = SimpleNamespace(
        keywords=[],  # No project keywords or requirements
        required_skills=["Python"],
        skills=["Python"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python"],
        projects=[],
        experience=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.projects.score == 100.0
    assert "N/A" in scores.projects.explanation


def test_4_project_requirement_but_no_evidence():
    job = SimpleNamespace(
        keywords=["E-Commerce", "Machine Learning", "Recommendation Engine"],
        required_skills=["Python"],
        skills=["Python"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python"],
        projects=[],
        experience=[{
            "company": "Legacy Corp",
            "title": "Support Engineer",
            "description": "Monitored server logs and resolved customer tickets.",
            "responsibilities": ["Attended daily team meetings."],
            "technologies": ["Python"],
            "duration_months": 24,
        }],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.projects.score == 0.0
    assert "No candidate projects found" in scores.projects.explanation


def test_5_generic_responsibility_not_treated_as_project_evidence():
    job = SimpleNamespace(
        keywords=["Distributed Systems", "Microservices Platform"],
        required_skills=["Java"],
        skills=["Java"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Java"],
        projects=[],
        experience=[{
            "company": "Corp A",
            "title": "Developer",
            "description": "Collaborated with senior engineers and attended agile ceremonies.",
            "responsibilities": ["Participated in code reviews."],
            "technologies": ["Java"],
            "duration_months": 12,
        }],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    # Generic experience does NOT qualify as project implementation
    assert scores.projects.score == 0.0


def test_6_project_technology_matching():
    job = SimpleNamespace(
        keywords=["React", "Node.js", "Redis"],
        required_skills=["React", "Node.js"],
        skills=["React", "Node.js"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["React", "Node.js"],
        projects=[{
            "name": "Chat Application",
            "description": "Real-time chat using React and Node.js with Redis pub/sub.",
            "technologies": ["React", "Node.js", "Redis"],
        }],
        experience=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None, projects=resume.projects)
    assert scores.projects.score == 100.0
    assert set(scores.projects.matched_items) == {"React", "Node.js", "Redis"}


def test_7_experienced_implementation_deliverable_matching():
    job = SimpleNamespace(
        keywords=["E-Commerce Application", "React", "Node.js"],
        required_skills=["React", "Node.js"],
        skills=["React", "Node.js"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["React", "Node.js"],
        projects=[],
        experience=[{
            "company": "Enterprise Solutions",
            "title": "Senior Frontend Engineer",
            "description": "Built an e-commerce application using React and Node.js.",
            "responsibilities": ["Designed responsive product catalog components."],
            "technologies": ["React", "Node.js"],
            "duration_months": 48,
        }],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.projects.score > 0.0
    assert "React" in scores.projects.matched_items or "Node.js" in scores.projects.matched_items
