import pytest
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.matching import MatchMethod, MatchStatus, Requirement, RequirementKind
from app.services.matching_service import DeterministicRequirementMatcher, EvidenceBuilder
from app.services.scoring.component_scoring_service import ComponentScoringService


def _run_matcher(req_text: str, candidate_skills: list[str], projects: list[dict] = None) -> MatchStatus:
    matcher = DeterministicRequirementMatcher()
    resume = SimpleNamespace(skills=candidate_skills, certifications=[], education=[], experience=[], projects=projects or [])
    extracted = SimpleNamespace(
        candidate_name="Test Candidate",
        skills=candidate_skills,
        education=[],
        certifications=[],
        languages=[],
        experience=[],
        projects=projects or [],
    )
    evidence = EvidenceBuilder.build(extracted)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text=req_text)
    verdict = matcher.match(req, resume, evidence)
    return verdict.status


def test_phase4_2_test1_jenkins_and_github_actions_with_github_only():
    """TEST 1: Jenkins and GitHub Actions with candidate having only GitHub -> NOT MATCHED."""
    status = _run_matcher("Jenkins and GitHub Actions", ["GitHub"])
    assert status == MatchStatus.NO_MATCH


def test_phase4_2_test2_jenkins_and_github_actions_with_jenkins_only():
    """TEST 2: Jenkins and GitHub Actions with candidate having only Jenkins -> NOT MATCHED."""
    status = _run_matcher("Jenkins and GitHub Actions", ["Jenkins"])
    assert status == MatchStatus.NO_MATCH


def test_phase4_2_test3_jenkins_and_github_actions_with_github_actions_only():
    """TEST 3: Jenkins and GitHub Actions with candidate having only GitHub Actions -> NOT MATCHED."""
    status = _run_matcher("Jenkins and GitHub Actions", ["GitHub Actions"])
    assert status == MatchStatus.NO_MATCH


def test_phase4_2_test4_jenkins_and_github_actions_with_both():
    """TEST 4: Jenkins and GitHub Actions with candidate having both -> MATCHED."""
    status = _run_matcher("Jenkins and GitHub Actions", ["Jenkins", "GitHub Actions"])
    assert status == MatchStatus.MATCHED


def test_phase4_2_test5_machine_learning_and_linux_with_linux_only():
    """TEST 5: Machine Learning and Linux with candidate having only Linux -> NOT MATCHED."""
    status = _run_matcher("Machine Learning and Linux", ["Linux"])
    assert status == MatchStatus.NO_MATCH


def test_phase4_2_test6_machine_learning_and_linux_with_both():
    """TEST 6: Machine Learning and Linux with candidate having both -> MATCHED."""
    status = _run_matcher("Machine Learning and Linux", ["Machine Learning", "Linux"])
    assert status == MatchStatus.MATCHED


def test_phase4_2_test7_mongodb_and_mysql_with_mongodb_only():
    """TEST 7: MongoDB and MySQL with candidate having only MongoDB -> NOT MATCHED."""
    status = _run_matcher("MongoDB and MySQL", ["MongoDB"])
    assert status == MatchStatus.NO_MATCH


def test_phase4_2_test8_mongodb_and_mysql_with_both():
    """TEST 8: MongoDB and MySQL with candidate having both -> MATCHED."""
    status = _run_matcher("MongoDB and MySQL", ["MongoDB", "MySQL"])
    assert status == MatchStatus.MATCHED


def test_phase4_2_test9_jenkins_or_github_actions_with_github_actions():
    """TEST 9: Jenkins or GitHub Actions with candidate having GitHub Actions -> MATCHED."""
    status = _run_matcher("Jenkins or GitHub Actions", ["GitHub Actions"])
    assert status == MatchStatus.MATCHED


def test_phase4_2_test10_jenkins_or_github_actions_with_jenkins():
    """TEST 10: Jenkins or GitHub Actions with candidate having Jenkins -> MATCHED."""
    status = _run_matcher("Jenkins or GitHub Actions", ["Jenkins"])
    assert status == MatchStatus.MATCHED


def test_phase4_2_test11_valid_semantic_equivalence_preserved():
    """TEST 11: Legitimate aliases continue to resolve."""
    assert _run_matcher("React.js", ["React"]) == MatchStatus.MATCHED
    assert _run_matcher("Git", ["Git"]) == MatchStatus.MATCHED
    assert _run_matcher("GitHub", ["GitHub"]) == MatchStatus.MATCHED


def test_phase4_2_test12_candidate2_preferred_skills_audit():
    """TEST 12: Candidate 2 preferred skills deterministic audit."""
    matcher = DeterministicRequirementMatcher()
    candidate_skills = [
        "C++", "HTML", "CSS", "JavaScript", "Data Structures and Algorithms",
        "OOPS", "DBMS", "REST APIs", "React.js", "Node.js", "Express.js",
        "Next.js", "MySQL", "MongoDB", "VSCode", "Canva", "GitHub", "Git",
        "Postman", "Vercel", "Playwright",
    ]
    projects = [
        {"name": "Secure Voting System", "technologies": ["React.js", "Node.js", "Express.js", "MongoDB", "REST APIs"], "description": "Voting portal"},
        {"name": "Smart Trolleys", "technologies": ["IoT", "Embedded Systems", "C++", "Python"], "description": "Smart IoT shopping trolley"},
    ]
    resume = SimpleNamespace(skills=candidate_skills, certifications=[], education=[], experience=[], projects=projects)
    extracted = SimpleNamespace(
        candidate_name="Candidate 2",
        skills=candidate_skills,
        education=[],
        certifications=[],
        languages=[],
        experience=[],
        projects=projects,
    )
    evidence = EvidenceBuilder.build(extracted)

    # 1. Jenkins and GitHub Actions -> Candidate has GitHub only -> NO_MATCH
    v_cicd = matcher.match(Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Jenkins and GitHub Actions"), resume, evidence)
    assert v_cicd.status == MatchStatus.NO_MATCH

    # 2. IoT -> Project 2 has IoT -> MATCHED
    v_iot = matcher.match(Requirement(requirement_id="skill:2", kind=RequirementKind.SKILL, text="IoT"), resume, evidence)
    assert v_iot.status == MatchStatus.MATCHED
    assert any("project" in str(eid).lower() for eid in v_iot.evidence_ids)

    # 3. Embedded Systems -> Project 2 has Embedded Systems -> MATCHED
    v_es = matcher.match(Requirement(requirement_id="skill:3", kind=RequirementKind.SKILL, text="Embedded Systems"), resume, evidence)
    assert v_es.status == MatchStatus.MATCHED
    assert any("project" in str(eid).lower() for eid in v_es.evidence_ids)

    # ComponentScoringService preferred skills score for Candidate 2
    service = ComponentScoringService()
    job = SimpleNamespace(
        required_skills=[],
        preferred_skills=[
            "AWS", "Docker", "CI/CD", "Jenkins and GitHub Actions", "IoT",
            "Embedded Systems", "PLC Programming", "Machine Learning and Linux",
            "PostgreSQL", "Kubernetes",
        ],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    scores = service.score(resume, job, config=None, projects=projects, match_verdicts=None)
    # Matched: IoT, Embedded Systems (2 of 10 = 20.0%)
    assert scores.preferred_skills.score == 20.0
    assert "IoT" in scores.preferred_skills.matched_items
    assert "Embedded Systems" in scores.preferred_skills.matched_items
    assert "Jenkins and GitHub Actions" in scores.preferred_skills.missing_items
