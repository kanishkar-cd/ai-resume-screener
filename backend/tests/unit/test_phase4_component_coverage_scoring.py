import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.schemas.matching import MatchMethod, MatchStatus, MatchVerdict
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService


def test_phase4_test1_deterministic_match():
    """TEST 1: 10 required skills, 8 deterministic MATCHED, 2 UNMET -> 80% coverage."""
    service = ComponentScoringService()
    resume = SimpleNamespace(skills=["Python", "FastAPI", "PostgreSQL", "Redis", "Docker", "Git", "HTML", "CSS"])
    job = SimpleNamespace(
        required_skills=["Python", "FastAPI", "PostgreSQL", "Redis", "Docker", "Git", "HTML", "CSS", "Kubernetes", "AWS"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    scores = service.score(resume, job, config=None, match_verdicts=None)
    assert scores.skills.score == 80.0
    assert len(scores.skills.matched_items) == 8
    assert len(scores.skills.missing_items) == 2


def test_phase4_test2_llm_changes_final_result():
    """TEST 2: 8 deterministic MATCHED + 1 LLM MATCHED = 9/10 (90% coverage)."""
    service = ComponentScoringService()
    # Candidate lists Playwright in resume
    resume = SimpleNamespace(skills=["React.js", "Node.js", "Express.js", "Next.js", "MySQL", "MongoDB", "Git", "GitHub", "Playwright"])
    job = SimpleNamespace(
        required_skills=["React.js", "Node.js", "Express.js", "Next.js", "MySQL", "MongoDB", "Git", "GitHub", "Playwright", "AWS"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    # LLM confirmed verdict for Playwright (skill:9)
    verdicts = [
        MatchVerdict(
            requirement_id="skill:9",
            status=MatchStatus.MATCHED,
            confidence=0.95,
            evidence_ids=["skills:1"],
            reasoning="Playwright explicitly confirmed in tools evidence.",
            method=MatchMethod.LLM_CONFIRMED,
        )
    ]
    scores = service.score(resume, job, config=None, match_verdicts=verdicts)
    assert scores.skills.score == 90.0
    assert "Playwright" in scores.skills.matched_items
    assert "AWS" in scores.skills.missing_items


def test_phase4_test3_llm_rejected():
    """TEST 3: 8 deterministic MATCHED + 2 LLM NO_MATCH = 8/10 (80% coverage)."""
    service = ComponentScoringService()
    resume = SimpleNamespace(skills=["React.js", "Node.js", "Express.js", "Next.js", "MySQL", "MongoDB", "Git", "GitHub"])
    job = SimpleNamespace(
        required_skills=["React.js", "Node.js", "Express.js", "Next.js", "MySQL", "MongoDB", "Git", "GitHub", "Docker", "AWS"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    verdicts = [
        MatchVerdict(
            requirement_id="skill:9",
            status=MatchStatus.NO_MATCH,
            confidence=1.0,
            evidence_ids=[],
            reasoning="Docker not found in candidate profile.",
            method=MatchMethod.LLM_REJECTED,
        ),
        MatchVerdict(
            requirement_id="skill:10",
            status=MatchStatus.NO_MATCH,
            confidence=1.0,
            evidence_ids=[],
            reasoning="AWS not found in candidate profile.",
            method=MatchMethod.LLM_REJECTED,
        ),
    ]
    scores = service.score(resume, job, config=None, match_verdicts=verdicts)
    assert scores.skills.score == 80.0
    assert len(scores.skills.matched_items) == 8


def test_phase4_test4_llm_unresolved():
    """TEST 4: UNRESOLVED verdicts are not automatically counted as matched."""
    service = ComponentScoringService()
    resume = SimpleNamespace(skills=["React.js", "Node.js"])
    job = SimpleNamespace(
        required_skills=["React.js", "Node.js", "Basic Authentication"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    verdicts = [
        MatchVerdict(
            requirement_id="skill:3",
            status=MatchStatus.UNRESOLVED,
            confidence=0.5,
            evidence_ids=[],
            reasoning="Candidate has login but Basic Auth is ambiguous.",
            method=MatchMethod.LLM_UNRESOLVED,
        )
    ]
    scores = service.score(resume, job, config=None, match_verdicts=verdicts)
    # 2 matched out of 3 = 66.67%
    assert scores.skills.score == 66.67
    assert "Basic Authentication" in scores.skills.missing_items


def test_phase4_test5_preferred_separation():
    """TEST 5: Required and Preferred skills are evaluated as separate components."""
    service = ComponentScoringService()
    resume = SimpleNamespace(skills=["React.js"])
    job = SimpleNamespace(
        required_skills=["React.js"],
        preferred_skills=["Docker"],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    scores = service.score(resume, job, config=None, match_verdicts=None)
    assert scores.skills.score == 100.0
    assert scores.preferred_skills.score == 0.0


def test_phase4_test6_responsibility_separation():
    """TEST 6: Skill match does not automatically satisfy responsibility requirement without experiential proof."""
    service = ComponentScoringService()
    resume = SimpleNamespace(skills=["Git", "GitHub"], experience=[])
    job = SimpleNamespace(
        required_skills=["Git"],
        preferred_skills=[],
        responsibilities=["Use Git/GitHub for source-code management"],
        degree_requirements=[],
        experience_requirements=[],
    )
    verdicts = [
        MatchVerdict(
            requirement_id="responsibility:1",
            status=MatchStatus.UNRESOLVED,
            confidence=0.3,
            evidence_ids=[],
            reasoning="Keyword present in skills, but no experiential responsibility proof.",
            method=MatchMethod.LLM_UNRESOLVED,
        )
    ]
    scores = service.score(resume, job, config=None, match_verdicts=verdicts)
    assert scores.skills.score == 100.0
    assert scores.responsibilities.score == 0.0


def test_phase4_test7_project_llm_match():
    """TEST 7: LLM-confirmed project match increases project coverage."""
    service = ComponentScoringService()
    resume = SimpleNamespace(
        skills=[],
        projects=[{"name": "Secure Voting System", "description": "Built web-based voting portal", "technologies": ["React.js"]}],
    )
    job = SimpleNamespace(
        required_skills=[],
        preferred_skills=[],
        project_requirements=["Build responsive web interface"],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    verdicts = [
        MatchVerdict(
            requirement_id="project:1",
            status=MatchStatus.MATCHED,
            confidence=0.9,
            evidence_ids=["project:1"],
            reasoning="Secure Voting System demonstrates responsive web interface.",
            method=MatchMethod.LLM_CONFIRMED,
        )
    ]
    scores = service.score(resume, job, config=None, projects=resume.projects, match_verdicts=verdicts)
    assert scores.projects.score == 100.0
    assert len(scores.projects.matched_items) == 1


def test_phase4_test8_duplicate_requirement_protection():
    """TEST 8: Duplicate JD requirements are deduplicated and do not inflate score."""
    service = ComponentScoringService()
    resume = SimpleNamespace(skills=["React.js"])
    job = SimpleNamespace(
        required_skills=["React.js", "React", "React.js"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    scores = service.score(resume, job, config=None, match_verdicts=None)
    # Deduplicated to 1 required skill -> 100%
    assert scores.skills.score == 100.0
    assert len(scores.skills.matched_items) == 1
    assert len(scores.skills.missing_items) == 0


def test_phase4_test9_repeated_resume_evidence_protection():
    """TEST 9: Repeated mentions of a skill across resume sections do not double count."""
    service = ComponentScoringService()
    resume = SimpleNamespace(
        skills=["React.js"],
        projects=[
            {"name": "P1", "description": "Used React.js", "technologies": ["React.js"]},
            {"name": "P2", "description": "Built with React.js", "technologies": ["React.js"]},
        ],
        experience=[{"description": "Developed React.js apps", "technologies": ["React.js"]}],
    )
    job = SimpleNamespace(
        required_skills=["React.js", "Docker"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    scores = service.score(resume, job, config=None, projects=resume.projects, match_verdicts=None)
    # 1 matched out of 2 = 50%
    assert scores.skills.score == 50.0
    assert len(scores.skills.matched_items) == 1
    assert len(scores.skills.missing_items) == 1


def test_phase4_test10_certification_distinction():
    """TEST 10: Skill knowledge does not satisfy certification requirement."""
    service = ComponentScoringService()
    resume = SimpleNamespace(skills=["AWS"], certifications=[])
    job = SimpleNamespace(
        required_skills=[],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    config = SimpleNamespace(required_certifications=["AWS Certified Developer"])
    scores = service.score(resume, job, config=config, match_verdicts=None)
    assert scores.certifications.score == 0.0


def test_phase4_test11_education_distinction():
    """TEST 11: Technical skills do not satisfy education degree requirement."""
    service = ComponentScoringService()
    resume = SimpleNamespace(skills=["React.js", "Node.js", "MongoDB"], education=[])
    job = SimpleNamespace(
        required_skills=[],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=["Bachelor's Degree in Computer Science"],
        experience_requirements=[],
    )
    scores = service.score(resume, job, config=None, match_verdicts=None)
    assert scores.education.score == 0.0


def test_phase4_test12_effective_weights_and_overall_score():
    """TEST 12: Dynamic applicability and mathematical reproduction of overall score."""
    service = ComponentScoringService()
    resume = SimpleNamespace(
        skills=["React.js", "Node.js", "Express.js", "Next.js", "MySQL", "MongoDB", "Git", "GitHub"],
        education=[{"degree": "B.Tech", "field_of_study": "Computer Science"}],
        experience=[],
        projects=[],
        certifications=[],
    )
    job = SimpleNamespace(
        required_skills=["React.js", "Node.js", "Express.js", "Next.js", "MySQL", "MongoDB", "Git", "GitHub", "Playwright", "Docker"],
        preferred_skills=["Vercel", "Postman"],
        responsibilities=["Develop web applications", "Perform automated testing"],
        degree_requirements=["B.Tech"],
        experience_requirements=[],
    )
    # LLM confirms Playwright and Vercel
    verdicts = [
        MatchVerdict(requirement_id="skill:9", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["skills:1"], reasoning="Playwright match", method=MatchMethod.LLM_CONFIRMED),
        MatchVerdict(requirement_id="skill:11", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["skills:1"], reasoning="Vercel match", method=MatchMethod.LLM_CONFIRMED),
        MatchVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.90, evidence_ids=["skills:1"], reasoning="Role match", method=MatchMethod.LLM_CONFIRMED),
    ]

    components = service.score(resume, job, config=None, match_verdicts=verdicts)

    # Required Skills: 9/10 = 90.0%
    assert components.skills.score == 90.0
    # Preferred Skills: 1/2 = 50.0%
    assert components.preferred_skills.score == 50.0
    # Responsibilities: 1/2 = 50.0%
    assert components.responsibilities.score == 50.0
    # Education: 100.0%
    assert components.education.score == 100.0

    applicable = WeightCalculationService.applicable_categories(job, config=None)
    # Applicable: required_skills (30), responsibilities (25), preferred_skills (15), education (2) = 72 base points
    weighted, raw_total, weighted_total, effective_weights = WeightCalculationService.calculate(
        components, config=None, applicable_categories=applicable
    )
    # Effective weights sum to 100.0
    assert round(sum(effective_weights.values()), 1) == 100.0

    # Mathematical reproduction:
    # 90.0 * (30/72) + 50.0 * (25/72) + 50.0 * (15/72) + 100.0 * (2/72)
    # = 37.5 + 17.361 + 10.417 + 2.778 = 68.055... -> 68.06%
    assert round(weighted_total, 2) == 68.06
