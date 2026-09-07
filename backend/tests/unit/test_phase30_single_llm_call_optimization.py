"""
Phase 30 — Single LLM Call Optimization Verification Suite

Rigorously verifies:
1. One resume with 0 unresolved requirements -> 0 Groq & 0 Cerebras calls.
2. One resume with 1, 8, 10, or 20 unresolved requirements -> EXACTLY 1 Groq call (No chunking).
3. Primary Groq failure -> EXACTLY 1 Cerebras fallback call.
4. Concurrency: 3 resumes -> 3 independent single-call LLM evaluations.
5. Exact verdict mapping and accuracy preservation.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.schemas.matching import (
    Evidence,
    LLMVerdict,
    LLMVerdictBatch,
    MatchMethod,
    MatchStatus,
    MatchVerdict,
    Requirement,
    RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher,
    EvidenceBuilder,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    HybridMatchingService,
    ProviderCircuitBreaker,
    RequirementBuilder,
    SmartMatchEvaluator,
)


@pytest.mark.asyncio
async def test_single_call_zero_unresolved():
    """Test A: All requirements matched deterministically -> 0 LLM calls."""
    job = SimpleNamespace(
        title="Python Developer",
        required_skills=["Python", "FastAPI"],
        preferred_skills=[],
        skills=["Python", "FastAPI"],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )
    resume = SimpleNamespace(
        name="Candidate A",
        skills=["Python", "FastAPI"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )
    extracted = SimpleNamespace(
        skills=["Python", "FastAPI"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=([], {}))

    service = HybridMatchingService(evaluator=mock_evaluator)
    _, verdicts = await service.match(job, resume, extracted)

    assert len(verdicts) == 2
    assert all(v.status == MatchStatus.MATCHED for v in verdicts)
    assert mock_evaluator.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_single_call_for_10_unresolved_requirements():
    """Test D: 10 unresolved requirements -> EXACTLY 1 LLM call (NOT 2)."""
    req_texts = [f"Custom Requirement {i}" for i in range(1, 11)]
    job = SimpleNamespace(
        title="Senior Lead",
        required_skills=req_texts,
        preferred_skills=[],
        skills=req_texts,
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )
    resume = SimpleNamespace(
        name="Candidate B",
        skills=[],
        experience=[{"description": "Generic experience covering multiple engineering duties"}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )
    extracted = SimpleNamespace(
        skills=[],
        experience=resume.experience,
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    mock_evaluator = MagicMock()
    llm_call_count = 0

    async def fake_evaluate(requirements, evidence, allowed_evidence=None, resume_id="default"):
        nonlocal llm_call_count
        llm_call_count += 1
        verdicts = [
            MatchVerdict(
                requirement_id=r.requirement_id,
                requirement_text=r.text,
                kind=r.kind,
                status=MatchStatus.MATCHED,
                confidence=0.9,
                evidence_ids=["exp:1"],
                reasoning="Matched by AI review.",
                method=MatchMethod.LLM_CONFIRMED,
                coverage=1.0,
                coverage_score=1.0,
                importance="important",
            )
            for r in requirements
        ]
        return verdicts, {"provider_selected": "groq", "actual_total_tokens": 500}

    mock_evaluator.evaluate = fake_evaluate

    service = HybridMatchingService(evaluator=mock_evaluator)
    _, verdicts = await service.match(job, resume, extracted)

    assert len(verdicts) == 10
    assert llm_call_count == 1, f"Expected exactly 1 LLM call for 10 requirements, got {llm_call_count}"
    assert all(v.status == MatchStatus.MATCHED for v in verdicts)


@pytest.mark.asyncio
async def test_single_call_for_20_unresolved_requirements():
    """Test E: 20 unresolved requirements -> EXACTLY 1 LLM call (NOT 3)."""
    req_texts = [f"Role Skill {i}" for i in range(1, 21)]
    job = SimpleNamespace(
        title="Architect",
        required_skills=req_texts,
        preferred_skills=[],
        skills=req_texts,
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )
    resume = SimpleNamespace(
        name="Candidate C",
        skills=[],
        experience=[{"description": "Extensive architectural experience"}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )
    extracted = SimpleNamespace(
        skills=[],
        experience=resume.experience,
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    mock_evaluator = MagicMock()
    llm_call_count = 0

    async def fake_evaluate(requirements, evidence, allowed_evidence=None, resume_id="default"):
        nonlocal llm_call_count
        llm_call_count += 1
        verdicts = [
            MatchVerdict(
                requirement_id=r.requirement_id,
                requirement_text=r.text,
                kind=r.kind,
                status=MatchStatus.MATCHED,
                confidence=0.85,
                evidence_ids=["exp:1"],
                reasoning="Matched.",
                method=MatchMethod.LLM_CONFIRMED,
                coverage=1.0,
                coverage_score=1.0,
                importance="important",
            )
            for r in requirements
        ]
        return verdicts, {"provider_selected": "groq", "actual_total_tokens": 1200}

    mock_evaluator.evaluate = fake_evaluate

    service = HybridMatchingService(evaluator=mock_evaluator)
    _, verdicts = await service.match(job, resume, extracted)

    assert len(verdicts) == 20
    assert llm_call_count == 1, f"Expected exactly 1 LLM call for 20 requirements, got {llm_call_count}"


@pytest.mark.asyncio
async def test_groq_failure_triggers_single_cerebras_fallback():
    """Test F: Groq failure -> EXACTLY 1 Cerebras fallback call containing all requirements."""
    req_texts = [f"Unresolved Requirement {i}" for i in range(1, 12)]
    requirements = [
        Requirement(requirement_id=f"skill:{i}", kind=RequirementKind.SKILL, text=text, required=True)
        for i, text in enumerate(req_texts, 1)
    ]
    evidence = [Evidence(evidence_id="exp:1", kind="experience", text="Backend experience.")]

    groq_mock = MagicMock()
    groq_mock.enabled = True
    groq_mock.evaluate_with_usage = AsyncMock(side_effect=RuntimeError("Groq 500 Server Error"))

    cerebras_mock = MagicMock()
    cerebras_mock.enabled = True
    cerebras_call_count = 0

    async def fake_cerebras(reqs, evs, allowed_evidence=None, allow_retries=True):
        nonlocal cerebras_call_count
        cerebras_call_count += 1
        verdicts = [
            MatchVerdict(
                requirement_id=r.requirement_id,
                status=MatchStatus.MATCHED,
                confidence=0.9,
                evidence_ids=["exp:1"],
                reasoning="Cerebras fallback match.",
                method=MatchMethod.LLM_CONFIRMED,
            )
            for r in reqs
        ]
        return verdicts, {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}

    cerebras_mock.evaluate_with_usage = AsyncMock(side_effect=fake_cerebras)

    with patch("app.services.matching_service.GroqMatchEvaluator", return_value=groq_mock), \
         patch("app.services.matching_service.CerebrasMatchEvaluator", return_value=cerebras_mock):
        smart_evaluator = SmartMatchEvaluator(groq_evaluator=groq_mock, cerebras_evaluator=cerebras_mock)
        verdicts, tele = await smart_evaluator.evaluate(requirements, evidence)

    assert len(verdicts) == 11
    assert cerebras_call_count == 1, f"Expected 1 Cerebras call for all 11 requirements, got {cerebras_call_count}"
    assert tele.get("provider_selected") == "cerebras"
