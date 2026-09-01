import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, EvidencePrefilter,
    GroqMatchEvaluator, HybridMatchingService, RequirementBuilder,
)
from app.services.scoring.component_scoring_service import ComponentScoringService


# ==============================================================================
# 1. EVIDENCE ROUTING & PREFILTER TESTS
# ==============================================================================

def test_event_driven_services_makes_asynchronous_programming_llm_eligible():
    """Verify 'event-driven services' makes 'asynchronous programming' eligible in prefilter."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="asynchronous programming")
    ev = [
        Evidence(evidence_id="experience:1", kind="experience", text="Architected event-driven services and async workers using RabbitMQ"),
    ]
    selected = prefilter.select(req, ev)
    assert len(selected) == 1
    assert selected[0].evidence_id == "experience:1"


def test_rbac_makes_authorization_llm_eligible():
    """Verify 'RBAC / role-based access' makes 'authorization' eligible in prefilter."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")
    ev = [
        Evidence(evidence_id="experience:1", kind="experience", text="Enforced role-based access control (RBAC) across microservices"),
    ]
    selected = prefilter.select(req, ev)
    assert len(selected) == 1
    assert selected[0].evidence_id == "experience:1"


def test_jwt_makes_authentication_llm_eligible():
    """Verify 'JWT token security' makes 'authentication' eligible in prefilter."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authentication")
    ev = [
        Evidence(evidence_id="experience:1", kind="experience", text="Implemented JWT token authentication and user sessions"),
    ]
    selected = prefilter.select(req, ev)
    assert len(selected) == 1
    assert selected[0].evidence_id == "experience:1"


def test_mobile_first_makes_responsive_design_llm_eligible():
    """Verify 'mobile-first layouts' makes 'responsive design' eligible in prefilter."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="responsive design")
    ev = [
        Evidence(evidence_id="project:1", kind="project", text="Crafted mobile-first layouts using CSS grid and flexbox"),
    ]
    selected = prefilter.select(req, ev)
    assert len(selected) == 1
    assert selected[0].evidence_id == "project:1"


def test_github_actions_makes_cicd_llm_eligible():
    """Verify 'GitHub Actions pipelines' makes 'CI/CD' eligible in prefilter."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="CI/CD")
    ev = [
        Evidence(evidence_id="experience:1", kind="experience", text="Automated deployment pipelines with GitHub Actions"),
    ]
    selected = prefilter.select(req, ev)
    assert len(selected) == 1
    assert selected[0].evidence_id == "experience:1"


def test_absent_skill_zero_evidence_not_eligible_for_llm():
    """Verify absent skills with zero evidence (Kubernetes) return empty from prefilter (0 LLM calls)."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="Kubernetes")
    ev = [
        Evidence(evidence_id="experience:1", kind="experience", text="Developed Python web APIs"),
    ]
    selected = prefilter.select(req, ev)
    assert len(selected) == 0


# ==============================================================================
# 2. RESPONSIBILITY SCORING & PROPORTIONAL COVERAGE TESTS
# ==============================================================================

@pytest.mark.parametrize("satisfied_count,expected_status,expected_coverage,expected_score", [
    (0, MatchStatus.UNRESOLVED, 0.0, 0.0),
    (1, MatchStatus.PARTIALLY_MATCHED, 0.25, 25.0),
    (2, MatchStatus.MATCHED, 0.50, 50.0),
    (3, MatchStatus.MATCHED, 0.75, 75.0),
    (4, MatchStatus.MATCHED, 1.00, 100.0),
])
def test_four_concept_responsibility_scoring_and_status(satisfied_count, expected_status, expected_coverage, expected_score):
    """Verify 4-concept responsibility: 0/4 -> UNRESOLVED(0%), 1/4 -> PARTIAL(25%), 2/4 -> MATCHED(50%), 3/4 -> MATCHED(75%), 4/4 -> MATCHED(100%)."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Design efficient MongoDB schemas, indexes, queries, and aggregation pipelines",
    )
    
    concept_phrases = [
        "MongoDB schemas",
        "database indexes",
        "optimized queries",
        "aggregation pipelines",
    ]
    evidence_text = ", ".join(concept_phrases[:satisfied_count]) if satisfied_count > 0 else "Unrelated administrative tasks"
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text=evidence_text)]
    resume = SimpleNamespace(skills=[], experience=[{"description": evidence_text}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == expected_status
    assert round(verdict.coverage, 2) == round(expected_coverage, 2)

    score_result = scoring_svc.score(resume, job, config=None, match_verdicts=[verdict])
    assert round(score_result.responsibilities.score, 1) == round(expected_score, 1)


@pytest.mark.parametrize("satisfied_count,expected_status,expected_coverage,expected_score", [
    (0, MatchStatus.UNRESOLVED, 0.0, 0.0),
    (1, MatchStatus.PARTIALLY_MATCHED, 0.20, 20.0),
    (2, MatchStatus.MATCHED, 0.40, 40.0),
    (3, MatchStatus.MATCHED, 0.60, 60.0),
    (4, MatchStatus.MATCHED, 0.80, 80.0),
    (5, MatchStatus.MATCHED, 1.00, 100.0),
])
def test_five_concept_responsibility_scoring_and_status(satisfied_count, expected_status, expected_coverage, expected_score):
    """Verify 5-concept responsibility: 0/5(0%), 1/5(20%), 2/5(40%), 3/5(60%), 4/5(80%), 5/5(100%)."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Develop scalable applications using MongoDB, Express.js, React.js, and Node.js",
    )
    concept_phrases = [
        "scalable applications",
        "MongoDB",
        "Express.js",
        "React.js",
        "Node.js",
    ]
    evidence_text = ", ".join(concept_phrases[:satisfied_count]) if satisfied_count > 0 else "Unrelated tasks"
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text=evidence_text)]
    resume = SimpleNamespace(skills=[], experience=[{"description": evidence_text}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == expected_status
    assert round(verdict.coverage, 2) == round(expected_coverage, 2)

    score_result = scoring_svc.score(resume, job, config=None, match_verdicts=[verdict])
    assert round(score_result.responsibilities.score, 1) == round(expected_score, 1)


def test_single_concept_responsibility_scoring_and_status():
    """Verify single concept responsibility: 1/1 -> MATCHED(100%), 0/1 -> UNRESOLVED(0%)."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Implement Redis caching",
    )
    
    # 1/1 case
    ev_matched = [Evidence(evidence_id="experience:1", kind="experience", text="Configured Redis caching for API responses")]
    resume_matched = SimpleNamespace(skills=[], experience=[{"description": "Configured Redis caching"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    verdict_matched = matcher.match(req, resume_matched, ev_matched)
    assert verdict_matched.status == MatchStatus.MATCHED
    assert verdict_matched.coverage == 1.00
    score_res = scoring_svc.score(resume_matched, job, config=None, match_verdicts=[verdict_matched])
    assert score_res.responsibilities.score == 100.0

    # 0/1 case
    ev_unmet = [Evidence(evidence_id="experience:1", kind="experience", text="Wrote CSS styles")]
    resume_unmet = SimpleNamespace(skills=[], experience=[{"description": "Wrote CSS styles"}], projects=[], education=[], certifications=[], languages=[])
    verdict_unmet = matcher.match(req, resume_unmet, ev_unmet)
    assert verdict_unmet.status == MatchStatus.UNRESOLVED
    assert verdict_unmet.coverage == 0.00
    score_res_unmet = scoring_svc.score(resume_unmet, job, config=None, match_verdicts=[verdict_unmet])
    assert score_res_unmet.responsibilities.score == 0.0


# ==============================================================================
# 3. ANTI-HALLUCINATION PROTECTIONS
# ==============================================================================

@pytest.mark.asyncio
async def test_anti_hallucination_rules():
    """Verify strict anti-hallucination: JS != Next.js, Backend != Docker, Backend != AWS, Generic collaboration != Mentoring."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    # Resume only mentions JavaScript and general backend
    resume = SimpleNamespace(skills=["JavaScript", "Backend Development"], experience=[{"description": "Worked with developers on web projects"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["JavaScript", "Backend Development"], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    
    job = SimpleNamespace(
        required_skills=["Next.js", "Docker", "AWS"],
        preferred_skills=[],
        skills=["Next.js", "Docker", "AWS"],
        responsibilities=["Mentor junior developers"],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    verdict_by_text = {getattr(v, "requirement_text", ""): v for v in verdicts}

    # Next.js, Docker, AWS have zero evidence -> directly NO_MATCH with 0 LLM calls
    assert verdict_by_text["Next.js"].status == MatchStatus.NO_MATCH
    assert verdict_by_text["Docker"].status == MatchStatus.NO_MATCH
    assert verdict_by_text["AWS"].status == MatchStatus.NO_MATCH
    
    # Generic collaboration != Mentoring (must NEVER be MATCHED)
    assert verdict_by_text["Mentor junior developers"].status != MatchStatus.MATCHED
