import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.matching import (
    Evidence, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, GroqMatchEvaluator, HybridMatchingService,
)
from app.services.scoring.component_scoring_service import ComponentScoringService


def test_phase14_75_percent_coverage_matched():
    """JD: Python, Kubernetes, Redis, Neon vs Resume: Kubernetes, Redis, Neon -> 75% MATCHED."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Work with Python, Kubernetes, Redis and Neon.",
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    evidence = [
        Evidence(
            evidence_id="project:1",
            kind="project",
            text="Built microservices using Kubernetes, Redis caching, and Neon serverless Postgres.",
        )
    ]
    v = matcher.match(req, resume, evidence)
    assert v.status == MatchStatus.MATCHED
    assert v.coverage == 0.75
    assert "python" in [c.casefold() for c in v.missing_concepts]
    assert len(v.matched_concepts) == 3


def test_phase14_25_percent_coverage_partially_matched():
    """JD: Python, Kubernetes, Redis, Neon vs Resume: Redis -> 25% PARTIALLY_MATCHED."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Work with Python, Kubernetes, Redis and Neon.",
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    evidence = [
        Evidence(
            evidence_id="experience:1",
            kind="experience",
            text="Configured Redis cache clusters for high throughput.",
        )
    ]
    v = matcher.match(req, resume, evidence)
    assert v.status == MatchStatus.PARTIALLY_MATCHED
    assert v.coverage == 0.25
    assert len(v.matched_concepts) == 1
    assert len(v.missing_concepts) == 3


def test_phase14_0_percent_coverage_unmatched():
    """JD: Python, Kubernetes, Redis, Neon vs Resume: Java, MySQL, Spring Boot -> 0% UNRESOLVED/UNMATCHED."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Work with Python, Kubernetes, Redis and Neon.",
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    evidence = [
        Evidence(
            evidence_id="experience:1",
            kind="experience",
            text="Developed enterprise backend services using Java, MySQL, and Spring Boot.",
        )
    ]
    v = matcher.match(req, resume, evidence)
    assert v.status in {MatchStatus.UNRESOLVED, MatchStatus.UNMATCHED, MatchStatus.NO_MATCH}
    assert v.coverage == 0.0
    assert len(v.matched_concepts) == 0


def test_phase14_50_percent_coverage_matched():
    """JD: Python, Kubernetes, Redis, Neon vs Resume: Kubernetes and Redis -> 50% MATCHED (>=45%)."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Work with Python, Kubernetes, Redis and Neon.",
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    evidence = [
        Evidence(
            evidence_id="project:1",
            kind="project",
            text="Deployed Kubernetes clusters and managed Redis caching layers.",
        )
    ]
    v = matcher.match(req, resume, evidence)
    assert v.status == MatchStatus.MATCHED
    assert v.coverage == 0.50


def test_phase14_45_percent_threshold_boundary():
    """Exact 45% boundary classification -> MATCHED."""
    matcher = DeterministicRequirementMatcher()
    # 20 distinct concepts
    req_terms = [f"item{i}" for i in range(1, 21)]
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Support " + ", ".join(req_terms),
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    # 9 supported (9/20 = 45%)
    evidence = [
        Evidence(
            evidence_id="project:1",
            kind="project",
            text="Implemented " + " ".join(req_terms[:9]),
        )
    ]
    v = matcher.match(req, resume, evidence)
    assert v.coverage == 0.45
    assert v.status == MatchStatus.MATCHED


def test_phase14_scoring_component_aggregate_coverage():
    """Verifies aggregate responsibility component scoring with individual coverage values."""
    scoring = ComponentScoringService()
    job = SimpleNamespace(
        required_skills=[], preferred_skills=[], responsibilities=["R1", "R2", "R3", "R4", "R5"],
        degree_requirements=[], experience_requirements=[],
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[], education=[], certifications=[])
    
    verdicts = [
        MatchVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=1.0, coverage=1.0, method=MatchMethod.EXACT),
        MatchVerdict(requirement_id="responsibility:2", status=MatchStatus.MATCHED, confidence=1.0, coverage=0.75, method=MatchMethod.ALIAS),
        MatchVerdict(requirement_id="responsibility:3", status=MatchStatus.MATCHED, confidence=1.0, coverage=0.50, method=MatchMethod.ALIAS),
        MatchVerdict(requirement_id="responsibility:4", status=MatchStatus.PARTIALLY_MATCHED, confidence=0.25, coverage=0.25, method=MatchMethod.ALIAS),
        MatchVerdict(requirement_id="responsibility:5", status=MatchStatus.NO_MATCH, confidence=0.0, coverage=0.0, method=None),
    ]

    components = scoring.score(resume, job, config=None, match_verdicts=verdicts)
    # Average coverage: (1.0 + 0.75 + 0.50 + 0.25 + 0.0) / 5 = 2.50 / 5 = 50.0%
    assert components.responsibilities.score == 50.0
    # Matched items count: R1, R2, R3 (status MATCHED)
    assert len(components.responsibilities.matched_items) == 3


@pytest.mark.asyncio
async def test_phase14_deterministic_matched_llm_bypassed():
    """Deterministic coverage >= 45% results in MATCHED and 0 LLM calls."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    evaluator_mock.evaluate = AsyncMock(return_value=[])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Work with Python, Kubernetes, Redis and Neon."])
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    extracted = SimpleNamespace(
        projects=[{
            "name": "Microservices Project",
            "description": "Deployed services with Kubernetes, Redis, and Neon Postgres.",
            "technologies": ["Kubernetes", "Redis", "Neon"],
        }]
    )

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].coverage == 0.75
    # LLM must be bypassed (0 calls)
    assert evaluator_mock.evaluate.call_count == 0
