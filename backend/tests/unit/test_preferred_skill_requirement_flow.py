import pytest
from types import SimpleNamespace
from app.schemas.matching import RequirementKind, MatchStatus
from app.services.matching_service import RequirementBuilder, DeterministicRequirementMatcher, EvidenceBuilder
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.bonus_service import BonusService
from app.services.scoring.weight_calculation_service import WeightCalculationService


def test_1_required_skill_only():
    job = SimpleNamespace(
        required_skills=["React", "Node.js"],
        preferred_skills=[],
        skills=["React", "Node.js"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
    )
    reqs = RequirementBuilder.build(job, config=None)
    assert len(reqs) == 2
    assert all(r.kind == RequirementKind.SKILL and r.required is True for r in reqs)


def test_2_preferred_skill_only():
    job = SimpleNamespace(
        required_skills=[],
        preferred_skills=["Docker", "AWS"],
        skills=["Docker", "AWS"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
    )
    reqs = RequirementBuilder.build(job, config=None)
    assert len(reqs) == 2
    assert all(r.kind == RequirementKind.SKILL and r.required is False for r in reqs)


def test_3_required_and_preferred_together():
    job = SimpleNamespace(
        required_skills=["JavaScript", "React", "Node.js", "MongoDB"],
        preferred_skills=["Docker", "AWS"],
        skills=["JavaScript", "React", "Node.js", "MongoDB", "Docker", "AWS"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
    )
    reqs = RequirementBuilder.build(job, config=None)
    assert len(reqs) == 6
    req_map = {r.text: r.required for r in reqs}
    assert req_map["JavaScript"] is True
    assert req_map["React"] is True
    assert req_map["Node.js"] is True
    assert req_map["MongoDB"] is True
    assert req_map["Docker"] is False
    assert req_map["AWS"] is False


def test_4_missing_preferred_skill_does_not_penalize_required_score():
    job = SimpleNamespace(
        required_skills=["JavaScript", "React", "Node.js", "MongoDB"],
        preferred_skills=["Docker", "AWS"],
        skills=["JavaScript", "React", "Node.js", "MongoDB", "Docker", "AWS"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["JavaScript", "React", "Node.js", "MongoDB"],
        certifications=[],
        experience=[],
        education=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    assert scores.skills.score == 100.0  # 4/4 required skills matched
    assert scores.skills.matched_items == ["JavaScript", "React", "Node.js", "MongoDB"]
    assert scores.skills.missing_items == []

    # Bonus calculation for candidate missing preferred skills
    bonus_total, bonus_items = BonusService.calculate(resume, job, config=None, components=scores)
    assert bonus_total == 0.0


def test_5_preferred_skill_alias_matching():
    job = SimpleNamespace(
        required_skills=["Python"],
        preferred_skills=["AWS", "Kubernetes"],
        skills=["Python", "AWS", "Kubernetes"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
    )
    resume = SimpleNamespace(
        skills=["Python", "Amazon Web Services", "K8s"],
        certifications=[],
        experience=[],
        education=[],
    )
    reqs = RequirementBuilder.build(job, config=None)
    matcher = DeterministicRequirementMatcher()
    evidence = EvidenceBuilder.build(resume)

    verdicts = [matcher.match(r, resume, evidence) for r in reqs]
    verdict_map = {r.text: v.status for r, v in zip(reqs, verdicts, strict=True)}
    assert verdict_map["AWS"] == MatchStatus.MATCHED
    assert verdict_map["Kubernetes"] == MatchStatus.MATCHED

    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)
    bonus_total, bonus_items = BonusService.calculate(resume, job, config=None, components=scores)
    assert bonus_total == 4.0  # 2 pts each for AWS and Kubernetes


def test_6_preferred_skill_in_multiple_sections_counted_once():
    job = SimpleNamespace(
        required_skills=["Python"],
        preferred_skills=["Docker"],
        skills=["Python", "Docker"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python", "Docker"],
        certifications=["Docker Certified Associate"],
        experience=[{"company": "ABC", "technologies": ["Docker"], "description": "Used Docker containers", "responsibilities": []}],
        projects=[{"name": "App", "technologies": ["Docker"], "description": "Dockerized app"}],
        education=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None, projects=resume.projects)
    bonus_total, bonus_items = BonusService.calculate(
        resume, job, config=None, components=scores, projects=resume.projects
    )
    # Docker appears in skills, certs, experience, and projects but bonus must be exactly 2.0 (counted once)
    assert bonus_total == 2.0
    assert len(bonus_items) == 1
    assert bonus_items[0].rule_name == "PREFERRED_SKILLS"


def test_7_preferred_skills_do_not_enter_required_denominator():
    job = SimpleNamespace(
        required_skills=["JavaScript", "React", "Node.js", "MongoDB"],
        preferred_skills=["Docker", "AWS", "Redis", "GraphQL"],
        skills=["JavaScript", "React", "Node.js", "MongoDB", "Docker", "AWS", "Redis", "GraphQL"],
        degree_requirements=[],
        responsibilities=[],
        certifications=[],
        keywords=[],
        experience_requirements=[],
    )
    # Candidate matches 2 out of 4 required skills, and 2 preferred skills
    resume = SimpleNamespace(
        skills=["React", "Node.js", "Docker", "AWS"],
        certifications=[],
        experience=[],
        education=[],
    )
    scorer = ComponentScoringService()
    scores = scorer.score(resume, job, config=None)

    # Denominator must be 4 (not 8) -> 2/4 = 50.0%
    assert scores.skills.score == 50.0
    assert len(scores.skills.missing_items) == 2
    assert "JavaScript" in scores.skills.missing_items
    assert "MongoDB" in scores.skills.missing_items
