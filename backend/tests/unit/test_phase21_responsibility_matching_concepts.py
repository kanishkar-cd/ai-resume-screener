import pytest
from types import SimpleNamespace

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import DeterministicRequirementMatcher
from app.services.scoring.component_scoring_service import ComponentScoringService


def test_1_four_concepts_two_satisfied_matched_50_percent():
    """1. 4 concepts, 2 satisfied -> MATCHED, 50%."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Design efficient MongoDB schemas, indexes, queries, and aggregation pipelines",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Designed MongoDB schemas and created database indexes for fast retrieval"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Designed MongoDB schemas and created database indexes"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.coverage == 0.50
    assert "2 of 4 responsibility concepts" in verdict.reasoning

    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[verdict])
    assert scores.responsibilities.score == 50.0


def test_2_four_concepts_three_satisfied_matched_75_percent():
    """2. 4 concepts, 3 satisfied -> MATCHED, 75%."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Design efficient MongoDB schemas, indexes, queries, and aggregation pipelines",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Designed MongoDB schemas, created indexes, and optimized complex SQL queries"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Designed MongoDB schemas, created indexes, and optimized complex SQL queries"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.coverage == 0.75
    assert "3 of 4 responsibility concepts" in verdict.reasoning

    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[verdict])
    assert scores.responsibilities.score == 75.0


def test_3_four_concepts_four_satisfied_matched_100_percent():
    """3. 4 concepts, 4 satisfied -> MATCHED, 100%."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Design efficient MongoDB schemas, indexes, queries, and aggregation pipelines",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Designed MongoDB schemas, managed indexes, optimized queries, and built aggregation pipelines"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Designed MongoDB schemas, managed indexes, optimized queries, and built aggregation pipelines"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.coverage == 1.00
    assert "4 of 4 responsibility concepts" in verdict.reasoning

    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[verdict])
    assert scores.responsibilities.score == 100.0


def test_4_four_concepts_one_satisfied_partial_25_percent():
    """4. 4 concepts, 1 satisfied -> PARTIALLY_MATCHED, 25%."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Design efficient MongoDB schemas, indexes, queries, and aggregation pipelines",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Created MongoDB schemas"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Created MongoDB schemas"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.PARTIALLY_MATCHED
    assert verdict.coverage == 0.25
    assert "only 1 of 4 responsibility concepts" in verdict.reasoning

    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[verdict])
    assert scores.responsibilities.score == 25.0


def test_5_five_concepts_two_satisfied_matched_40_percent():
    """5. 5 concepts, exactly 2 satisfied -> MATCHED, 40%."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Develop scalable applications using MongoDB, Express.js, React.js, and Node.js",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Built user interfaces in React.js and backend microservices with Node.js"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Built user interfaces in React.js and backend microservices with Node.js"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.coverage == 0.40

    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[verdict])
    assert scores.responsibilities.score == 40.0


def test_6_five_concepts_one_satisfied_partial_20_percent():
    """6. 5 concepts, 1 satisfied -> PARTIALLY_MATCHED, 20%."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Develop scalable applications using MongoDB, Express.js, React.js, and Node.js",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Built web pages in React.js"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Built web pages in React.js"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.PARTIALLY_MATCHED
    assert verdict.coverage == 0.20

    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[verdict])
    assert scores.responsibilities.score == 20.0


def test_7_single_concept_responsibility_matched():
    """7. Single-concept responsibility with valid evidence -> MATCHED."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Implement Redis caching",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Implemented in-memory Redis caching to reduce latency"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Implemented in-memory Redis caching"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.coverage == 1.00

    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[verdict])
    assert scores.responsibilities.score == 100.0


def test_8_semantic_responsibility_evidence_from_project():
    """8. Semantic responsibility evidence from PROJECT -> MATCHED."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Build reusable, responsive React components and user interfaces",
    )
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="Built reusable React components with responsive design for cross-platform devices"),
    ]
    resume = SimpleNamespace(skills=[], experience=[], projects=[{"description": "Built reusable React components with responsive design"}], education=[], certifications=[], languages=[])
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert "project:1" in verdict.evidence_ids


def test_9_semantic_responsibility_evidence_from_internship():
    """9. Semantic responsibility evidence from INTERNSHIP -> MATCHED."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Design and maintain database schemas and optimize queries",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Internship at Web Tech: Designed database schemas and optimized SQL queries"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Internship at Web Tech: Designed database schemas and optimized SQL queries"}], projects=[], education=[], certifications=[], languages=[])
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert "experience:1" in verdict.evidence_ids


def test_10_semantic_responsibility_evidence_from_experience():
    """10. Semantic responsibility evidence from EXPERIENCE -> MATCHED."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Implement secure authentication and role-based access workflows",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Implemented JWT authentication and RBAC authorization workflows across REST services"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Implemented JWT authentication and RBAC authorization"}], projects=[], education=[], certifications=[], languages=[])
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert "experience:1" in verdict.evidence_ids


def test_11_weak_unrelated_keyword_not_matched():
    """11. Weak unrelated keyword -> NOT MATCHED / UNRESOLVED."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Design and deploy Kubernetes clusters and Terraform infrastructure",
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Created website graphics using Adobe Photoshop and CSS"),
    ]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Created website graphics"}], projects=[], education=[], certifications=[], languages=[])
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.UNRESOLVED
    assert verdict.coverage == 0.0
