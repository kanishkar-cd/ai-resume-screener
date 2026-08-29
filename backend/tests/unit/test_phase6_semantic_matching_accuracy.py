import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, EvidencePrefilter, GroqMatchEvaluator, HybridMatchingService,
)
from app.services.scoring.component_scoring_service import ComponentScoringService


def _run_matcher(req_kind: RequirementKind, req_text: str, candidate_skills: list[str], projects: list[dict] = None, experience: list[dict] = None, education: list[dict] = None, certifications: list[str] = None) -> MatchVerdict:
    matcher = DeterministicRequirementMatcher()
    resume = SimpleNamespace(
        skills=candidate_skills,
        certifications=certifications or [],
        education=education or [],
        experience=experience or [],
        projects=projects or [],
    )
    extracted = SimpleNamespace(
        candidate_name="Test Candidate",
        skills=candidate_skills,
        education=education or [],
        certifications=certifications or [],
        languages=[],
        experience=experience or [],
        projects=projects or [],
    )
    evidence = EvidenceBuilder.build(extracted)
    req = Requirement(requirement_id="req:1", kind=req_kind, text=req_text, canonical_value=req_text)
    return matcher.match(req, resume, evidence)


def test_phase6_test1_exact_skill_match():
    """TEST 1: React.js in skills -> MATCHED."""
    v = _run_matcher(RequirementKind.SKILL, "React.js", ["React.js"])
    assert v.status == MatchStatus.MATCHED
    assert v.method in {MatchMethod.EXACT, MatchMethod.ALIAS}


def test_phase6_test2_project_technology_skill_match():
    """TEST 2: React.js in project technologies -> MATCHED."""
    projects = [{"name": "Web App", "technologies": ["React.js"], "description": "Frontend portal"}]
    v = _run_matcher(RequirementKind.SKILL, "React.js", [], projects=projects)
    assert v.status == MatchStatus.MATCHED


def test_phase6_test3_javascript_vs_typescript():
    """TEST 3: TypeScript requirement with candidate JavaScript only -> NO_MATCH."""
    v = _run_matcher(RequirementKind.SKILL, "TypeScript", ["JavaScript"])
    assert v.status == MatchStatus.NO_MATCH


def test_phase6_test4_aws_vs_vercel():
    """TEST 4: AWS requirement with candidate Vercel only -> NO_MATCH."""
    v = _run_matcher(RequirementKind.SKILL, "AWS", ["Vercel"])
    assert v.status == MatchStatus.NO_MATCH


def test_phase6_test5_github_vs_github_actions():
    """TEST 5: GitHub Actions requirement with candidate GitHub only -> NO_MATCH."""
    v = _run_matcher(RequirementKind.SKILL, "GitHub Actions", ["GitHub"])
    assert v.status == MatchStatus.NO_MATCH


def test_phase6_test6_mongodb_vs_mysql():
    """TEST 6: MySQL requirement with candidate MongoDB only -> NO_MATCH."""
    v = _run_matcher(RequirementKind.SKILL, "MySQL", ["MongoDB"])
    assert v.status == MatchStatus.NO_MATCH


def test_phase6_test7_skill_only_for_responsibility_requires_review():
    """TEST 7: Skills list alone does not deterministically satisfy action responsibility."""
    v = _run_matcher(
        RequirementKind.RESPONSIBILITY,
        "Build and maintain backend APIs using Node.js and Express.js",
        ["Node.js", "Express.js"],
    )
    # Must be UNRESOLVED so experiential context can be checked via LLM
    assert v.status == MatchStatus.UNRESOLVED


def test_phase6_test8_project_implementation_satisfies_responsibility():
    """TEST 8: Project implementation evidence satisfies responsibility."""
    projects = [{
        "name": "API Service",
        "technologies": ["Node.js", "Express.js"],
        "description": "Built and maintained backend APIs using Node.js and Express.js",
    }]
    v = _run_matcher(
        RequirementKind.RESPONSIBILITY,
        "Built and maintained backend APIs using Node.js and Express.js",
        [],
        projects=projects,
    )
    assert v.status == MatchStatus.MATCHED
    assert any("project" in str(eid) for eid in v.evidence_ids)


def test_phase6_test9_project_relevance_matching():
    """TEST 9: Project domain relevance matches project description."""
    projects = [{
        "name": "E-Commerce Store",
        "description": "Built an e-commerce shopping platform",
        "technologies": ["React.js"],
    }]
    v = _run_matcher(
        RequirementKind.PROJECT_RELEVANCE,
        "e-commerce shopping platform",
        [],
        projects=projects,
    )
    assert v.status == MatchStatus.MATCHED
    assert any("project" in str(eid) for eid in v.evidence_ids)


def test_phase6_test10_conjunction_and_semantics():
    """TEST 10: AND conjunction requires all sub-parts."""
    v_partial = _run_matcher(RequirementKind.SKILL, "MongoDB and MySQL", ["MongoDB"])
    assert v_partial.status == MatchStatus.NO_MATCH

    v_full = _run_matcher(RequirementKind.SKILL, "MongoDB and MySQL", ["MongoDB", "MySQL"])
    assert v_full.status == MatchStatus.MATCHED


def test_phase6_test11_alternative_or_semantics():
    """TEST 11: OR alternative satisfies on any valid option."""
    v_alt = _run_matcher(RequirementKind.SKILL, "Jenkins or GitHub Actions", ["GitHub Actions"])
    assert v_alt.status == MatchStatus.MATCHED


def test_phase6_test12_education_degree_rank_matching():
    """TEST 12: B.Tech satisfies Bachelor's degree requirement via taxonomy."""
    education = [{"degree": "B.Tech", "field_of_study": "Computer Science"}]
    v = _run_matcher(RequirementKind.DEGREE, "Bachelor's Degree", [], education=education)
    assert v.status == MatchStatus.MATCHED


def test_phase6_test13_anti_hallucination_evidence_id_validation():
    """TEST 13: LLM MATCHED verdict with invalid/fake evidence ID is downgraded to UNRESOLVED."""
    evaluator = GroqMatchEvaluator()
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="AWS")
    real_evidence = [Evidence(evidence_id="skills:1", kind="skills", text="React, Node.js", canonical_terms=["React", "Node.js"])]

    # Batch with fake evidence ID
    batch = SimpleNamespace(
        verdicts=[
            SimpleNamespace(
                requirement_id="skill:1",
                status="MATCHED",
                confidence=0.95,
                evidence_ids=["fake:999"],
                reasoning="Claimed match with non-existent evidence ID.",
            )
        ]
    )

    validated = evaluator._validate(batch, [req], real_evidence, allowed_evidence={"skill:1": {"skills:1"}})
    assert len(validated) == 1
    # Downgraded to UNRESOLVED due to invalid evidence_id
    assert validated[0].status == MatchStatus.UNRESOLVED
