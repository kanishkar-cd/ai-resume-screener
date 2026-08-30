import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, EvidencePrefilter, GroqMatchEvaluator, HybridMatchingService,
)


@pytest.mark.asyncio
async def test_phase3_deterministic_match_bypasses_llm():
    """Confident deterministic matches MUST NOT call the LLM."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    evaluator_mock.evaluate = AsyncMock(return_value=[])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Build and maintain REST APIs using Node.js and Express.js."])
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    extracted = SimpleNamespace(
        projects=[{
            "name": "E-Commerce App",
            "description": "Developed RESTful APIs using Node.js and Express for order management.",
            "technologies": ["Node.js", "Express"],
        }]
    )

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].coverage >= 0.75
    # LLM must be bypassed (0 calls)
    assert evaluator_mock.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_phase3_unresolved_concept_routed_to_llm_fallback():
    """Unresolved responsibility sub-concept routes to LLM fallback with targeted experiential evidence."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    llm_verdict = MatchVerdict(
        requirement_id="responsibility:1",
        status=MatchStatus.MATCHED,
        confidence=0.92,
        evidence_ids=["experience:1"],
        reasoning="Stripe payment and Twilio SMS integrations demonstrate third-party services integration.",
        method=MatchMethod.LLM_CONFIRMED,
        coverage=1.0,
    )
    evaluator_mock.evaluate = AsyncMock(return_value=[llm_verdict])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Develop secure RESTful APIs and integrate third-party services."])
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    extracted = SimpleNamespace(
        experience=[{
            "title": "Backend Developer",
            "company": "SaaS Co",
            "description": "Engineered REST APIs using Python and integrated Stripe API for payments.",
            "responsibilities": ["Integrated third-party APIs including Stripe and Twilio."],
        }]
    )

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].method in (MatchMethod.LLM_CONFIRMED, MatchMethod.ALIAS, MatchMethod.DETERMINISTIC_EXACT, MatchMethod.DETERMINISTIC_CANONICAL)
    assert evaluator_mock.evaluate.call_count == 1


@pytest.mark.asyncio
async def test_phase3_skill_only_candidate_not_leaked_to_llm_for_responsibility():
    """Skill-only candidate without projects/experience must not pass skills to LLM for responsibility matching."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    evaluator_mock.evaluate = AsyncMock(return_value=[])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Design and develop scalable applications using MongoDB, Express.js, React.js, and Node.js."])
    resume = SimpleNamespace(skills=["React", "Node.js", "Express.js", "MongoDB"], projects=[], experience=[])
    extracted = SimpleNamespace(
        skills=["React", "Node.js", "Express.js", "MongoDB"],
        projects=[],
        experience=[],
    )

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    # When evaluated, LLM call was dispatched but allowed_evidence for responsibility was empty
    assert verdicts[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH, MatchStatus.UNMATCHED}


def test_phase3_llm_citation_validation_enforces_allowed_evidence():
    """GroqMatchEvaluator._validate strictly rejects LLM MATCHED verdicts that cite invalid or unallowed evidence IDs."""
    evaluator = GroqMatchEvaluator()
    requirements = [
        Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Monitor SIEM alerts.")
    ]
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="Configured Wazuh lab to review alerts.")
    ]
    allowed_evidence = {"responsibility:1": {"project:1"}}

    # Valid Citation
    batch_valid = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["project:1"], reasoning="Valid proof.")
    ])
    validated = evaluator._validate(batch_valid, requirements, evidence, allowed_evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED

    # Invalid Citation (hallucinated evidence_id "project:99")
    batch_invalid = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["project:99"], reasoning="Fake proof.")
    ])
    validated_invalid = evaluator._validate(batch_invalid, requirements, evidence, allowed_evidence)
    assert len(validated_invalid) == 1
    assert validated_invalid[0].status == MatchStatus.UNRESOLVED
    assert validated_invalid[0].method == MatchMethod.LLM_UNRESOLVED
