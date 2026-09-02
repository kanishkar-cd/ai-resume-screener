import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.schemas.matching import Requirement, RequirementKind, Evidence, MatchStatus, MatchVerdict, MatchMethod
from app.services.matching_service import (
    CerebrasMatchEvaluator,
    CerebrasTokenBudgetGate,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    HybridMatchingService,
    ResumeQueueScheduler,
    SmartMatchEvaluator,
)


@pytest.mark.asyncio
async def test_max_3_concurrent_resumes_execution():
    """Verify ResumeQueueScheduler limits active concurrent tasks to at most 3 in-flight."""
    scheduler = ResumeQueueScheduler(max_concurrent=3)
    active_count = 0
    max_active = 0
    lock = asyncio.Lock()

    async def dummy_task(i: int):
        nonlocal active_count, max_active
        async with lock:
            active_count += 1
            if active_count > max_active:
                max_active = active_count
        await asyncio.sleep(0.05)
        async with lock:
            active_count -= 1
        return f"result_{i}"

    tasks = [scheduler.run_resume_task(f"resume_{i}", dummy_task(i)) for i in range(10)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 10
    assert max_active <= 3


@pytest.mark.asyncio
async def test_smart_routing_uses_groq_when_capacity_sufficient():
    """Verify SmartMatchEvaluator routes to Groq when safe remaining capacity is sufficient."""
    settings = SimpleNamespace(
        GROQ_API_KEY="mock_groq_key",
        CEREBRAS_API_KEY="mock_cerebras_key",
        ENABLE_HYBRID_MATCHING=True,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.80,
    )

    groq_mock = MagicMock()
    groq_mock.enabled = True
    groq_mock._payload.return_value = {"messages": [{"role": "user", "content": '{"requirements":[]}'}]}
    groq_mock.evaluate = AsyncMock(return_value=[MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, method=MatchMethod.LLM_CONFIRMED)])

    cerebras_mock = MagicMock()
    cerebras_mock.enabled = True
    cerebras_mock.evaluate = AsyncMock()

    evaluator = SmartMatchEvaluator(settings=settings, groq_evaluator=groq_mock, cerebras_evaluator=cerebras_mock)

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python")]
    evs = [Evidence(evidence_id="skills:1", kind="skills", text="Python")]

    verdicts, telemetry = await evaluator.evaluate(reqs, evs, resume_id="resume_101")

    assert telemetry["provider_selected"] == "groq"
    assert telemetry["resume_id"] == "resume_101"
    assert groq_mock.evaluate.called
    assert not cerebras_mock.evaluate.called


@pytest.mark.asyncio
async def test_smart_routing_proactive_cerebras_fallback_when_groq_insufficient():
    """Verify SmartMatchEvaluator routes IMMEDIATELY to Cerebras without waiting when Groq capacity is low."""
    settings = SimpleNamespace(
        GROQ_API_KEY="mock_groq_key",
        CEREBRAS_API_KEY="mock_cerebras_key",
        ENABLE_HYBRID_MATCHING=True,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.80,
    )

    groq_gate = GroqTokenBudgetGate.get_gate(settings)
    groq_gate.reset_gate()

    # Reserve 6,900 tokens out of 7,000 safe capacity -> only 100 available!
    groq_gate.reserved_in_flight = 6900

    groq_mock = MagicMock()
    groq_mock.enabled = True
    groq_mock._payload.return_value = {"messages": [{"role": "user", "content": '{"requirements":[{"requirement_id":"skill:1"}]}'}]}
    groq_mock.evaluate = AsyncMock()

    cerebras_mock = MagicMock()
    cerebras_mock.enabled = True
    cerebras_mock.evaluate = AsyncMock(return_value=[MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, method=MatchMethod.LLM_CONFIRMED)])
    cerebras_mock.evaluate_with_usage = AsyncMock(return_value=([MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, method=MatchMethod.LLM_CONFIRMED)], {"prompt_tokens": 2500, "completion_tokens": 150, "total_tokens": 2650}))

    evaluator = SmartMatchEvaluator(settings=settings, groq_evaluator=groq_mock, cerebras_evaluator=cerebras_mock)

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python")]
    evs = [Evidence(evidence_id="skills:1", kind="skills", text="Python")]

    t0 = asyncio.get_event_loop().time()
    verdicts, telemetry = await evaluator.evaluate(reqs, evs, resume_id="resume_102")
    t1 = asyncio.get_event_loop().time()

    # Routing decision must happen instantaneously (< 0.5s), NOT waiting 47s on Groq
    assert (t1 - t0) < 0.5
    assert telemetry["provider_selected"] == "cerebras"
    assert telemetry["fallback_reason"] == "groq_capacity_insufficient"
    assert telemetry["actual_total_tokens"] == 2650
    assert telemetry["actual_input_tokens"] == 2500
    assert telemetry["actual_output_tokens"] == 150
    assert cerebras_mock.evaluate_with_usage.called

    groq_gate.reset_gate()


@pytest.mark.asyncio
async def test_groq_429_triggers_immediate_cerebras_fallback():
    """Verify Groq API exception/429 triggers immediate fallback to Cerebras."""
    settings = SimpleNamespace(
        GROQ_API_KEY="mock_groq_key",
        CEREBRAS_API_KEY="mock_cerebras_key",
        ENABLE_HYBRID_MATCHING=True,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.80,
    )

    groq_mock = MagicMock()
    groq_mock.enabled = True
    groq_mock._payload.return_value = {"messages": [{"role": "user", "content": '{"requirements":[]}'}]}
    groq_mock.evaluate = AsyncMock(side_effect=RuntimeError("Groq 429 Rate Limit Exceeded"))

    cerebras_mock = MagicMock()
    cerebras_mock.enabled = True
    cerebras_mock.evaluate = AsyncMock(return_value=[MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, method=MatchMethod.LLM_CONFIRMED)])

    evaluator = SmartMatchEvaluator(settings=settings, groq_evaluator=groq_mock, cerebras_evaluator=cerebras_mock)

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python")]
    evs = [Evidence(evidence_id="skills:1", kind="skills", text="Python")]

    verdicts, telemetry = await evaluator.evaluate(reqs, evs, resume_id="resume_103")

    assert telemetry["provider_selected"] == "cerebras"
    assert "groq_error_" in telemetry["fallback_reason"]
    assert len(verdicts) == 1


def test_conservative_token_estimation():
    """Verify conservative token estimation math includes overhead safety buffer."""
    gate = GroqTokenBudgetGate.get_gate()
    payload = {
        "messages": [
            {"role": "system", "content": "You are a evaluator."},
            {"role": "user", "content": '{"requirements":[{"requirement_id":"1"},{"requirement_id":"2"}]}'},
        ]
    }
    estimate = gate.estimate_tokens(payload)

    # Estimate must be conservative (input + output + safety buffer > 200)
    assert estimate > 200


@pytest.mark.asyncio
async def test_isolated_resume_contexts():
    """Verify 2 parallel resumes maintain isolated requirement, evidence, and verdict contexts."""
    job = SimpleNamespace(required_skills=["Python"], skills=["Python"])

    resume1 = SimpleNamespace(id="res_1", candidate_name="Alice", skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ext1 = SimpleNamespace(skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])

    resume2 = SimpleNamespace(id="res_2", candidate_name="Bob", skills=["Java"], experience=[], projects=[], education=[], certifications=[], languages=[])
    ext2 = SimpleNamespace(skills=["Java"], experience=[], projects=[], education=[], certifications=[], languages=[])

    mock_eval = AsyncMock()
    mock_eval.evaluate.side_effect = lambda reqs, ev, allowed, resume_id="": ([], {})

    service = HybridMatchingService(evaluator=mock_eval)

    task1 = service.match(job, resume1, ext1)
    task2 = service.match(job, resume2, ext2)

    (enrich1, verdicts1), (enrich2, verdicts2) = await asyncio.gather(task1, task2)

    # Contexts must be isolated per candidate
    assert verdicts1[0].status == MatchStatus.MATCHED
    assert verdicts2[0].status == MatchStatus.NO_MATCH
