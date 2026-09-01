import pytest
from types import SimpleNamespace
from app.schemas.matching import RequirementKind, MatchStatus
from app.services.matching_service import RequirementBuilder, DeterministicRequirementMatcher, EvidenceBuilder
from app.services.scoring.component_scoring_service import ComponentScoringService


def test_case_1_responsive_design():
    job = SimpleNamespace(
        required_skills=["Responsive Design"],
        skills=["Responsive Design"],
        preferred_skills=[],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["HTML5", "CSS3"],
        experience=[{"company": "Tech", "description": "Developed responsive web design using CSS and Flexbox.", "responsibilities": [], "technologies": []}],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 100.0
    assert "Responsive Design" in scores.skills.matched_items


def test_case_2_state_management():
    job = SimpleNamespace(
        required_skills=["State Management"],
        skills=["State Management"],
        preferred_skills=[],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["React", "Redux"],
        experience=[{"company": "Tech", "description": "Implemented state management using Redux and Context API.", "responsibilities": [], "technologies": []}],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 100.0
    assert "State Management" in scores.skills.matched_items


def test_case_3_asynchronous_programming():
    job = SimpleNamespace(
        required_skills=["Asynchronous Programming"],
        skills=["Asynchronous Programming"],
        preferred_skills=[],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["JavaScript"],
        experience=[{"company": "Tech", "description": "Developed asynchronous JavaScript services and event loops.", "responsibilities": [], "technologies": []}],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 100.0
    assert "Asynchronous Programming" in scores.skills.matched_items


def test_case_4_rest_apis():
    job = SimpleNamespace(
        required_skills=["REST APIs"],
        skills=["REST APIs"],
        preferred_skills=[],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Developed RESTful APIs"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 100.0


def test_case_5_react_js_alias():
    job = SimpleNamespace(
        required_skills=["React.js"],
        skills=["React.js"],
        preferred_skills=[],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["ReactJS"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 100.0


def test_case_6_java_vs_javascript_no_false_positive():
    job = SimpleNamespace(
        required_skills=["Java"],
        skills=["Java"],
        preferred_skills=[],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["JavaScript", "TypeScript"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 0.0
    assert "Java" in scores.skills.missing_items


def test_case_7_cloud_computing_unmet():
    job = SimpleNamespace(
        required_skills=["Cloud Computing"],
        skills=["Cloud Computing"],
        preferred_skills=[],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["GitHub", "Git"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 0.0
    assert "Cloud Computing" in scores.skills.missing_items


def test_case_8_state_machine_does_not_match_state_management():
    job = SimpleNamespace(
        required_skills=["State Management"],
        skills=["State Management"],
        preferred_skills=[],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["State Machine Implementation"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 0.0
    assert "State Management" in scores.skills.missing_items


def test_case_9_database_does_not_match_database_management():
    job = SimpleNamespace(
        required_skills=["Database Management"],
        skills=["Database Management"],
        preferred_skills=[],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Database"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 0.0
    assert "Database Management" in scores.skills.missing_items


def test_case_10_required_skill_denominator_preservation():
    job = SimpleNamespace(
        required_skills=[
            "React.js", "JavaScript", "HTML5", "CSS3", "Responsive Design",
            "State Management", "Node.js", "Express.js", "REST APIs", "MongoDB",
        ],
        skills=[
            "React.js", "JavaScript", "HTML5", "CSS3", "Responsive Design",
            "State Management", "Node.js", "Express.js", "REST APIs", "MongoDB",
        ],
        preferred_skills=["Docker", "AWS"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    # Candidate matches 7 of the 10 required skills
    resume = SimpleNamespace(
        skills=["ReactJS", "JavaScript", "HTML5", "CSS3", "Node.js", "Express.js", "MongoDB"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    # 7 / 10 = 70.0%
    assert scores.skills.score == 70.0
    assert len(scores.skills.matched_items) == 7
    assert len(scores.skills.missing_items) == 3
