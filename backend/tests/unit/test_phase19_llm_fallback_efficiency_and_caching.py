import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    EvidenceBuilder, GroqMatchEvaluator, HybridMatchingService, RequirementBuilder,
)


@pytest.mark.asyncio
async def test_deterministic_matched_skill_zero_llm_calls():
    """1. Deterministically matched skill -> 0 LLM calls."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["Python", "SQL"], experience=[], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["Python", "SQL"], experience=[], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["Python", "SQL"], preferred_skills=[], skills=["Python", "SQL"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert len(verdicts) == 2
    assert all(v.status == MatchStatus.MATCHED for v in verdicts)
    assert mock_evaluator.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_deterministic_degree_zero_llm_calls():
    """2. Disabled degree requirements -> 0 requirements built and 0 LLM calls."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[], projects=[], education=[{"degree": "Bachelor of Technology"}], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=[], projects=[], education=resume.education, certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[], degree_requirements=["Bachelor's Degree"], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert len(verdicts) == 0
    assert mock_evaluator.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_deterministic_experience_duration_zero_llm_calls():
    """3. Deterministically resolved experience duration -> 0 LLM calls."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[{"duration_months": 36}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[], degree_requirements=[], experience_requirements=[{"display_value": "3+ Years", "minimum_months": 36}], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert mock_evaluator.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_preferred_skill_zero_evidence_zero_llm_calls():
    """4. Preferred skill with zero candidate evidence -> 0 LLM calls."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["Python"], experience=[], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["Python"], preferred_skills=["Terraform"], skills=["Python", "Terraform"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert len(verdicts) == 2
    assert mock_evaluator.evaluate.call_count == 0
    pref_verdict = next(v for v in verdicts if "Terraform" in getattr(v, "requirement_text", ""))
    assert pref_verdict.status == MatchStatus.NO_MATCH


@pytest.mark.asyncio
async def test_semantic_authorization_calls_llm():
    """5. Semantic authorization/RBAC -> LLM called with relevant experience evidence."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="RBAC in experience:1")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[{"description": "Implemented role-based access control and JWT permissions"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["authorization"], preferred_skills=[], skills=["authorization"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert mock_evaluator.evaluate.call_count == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].method == MatchMethod.LLM_CONFIRMED


@pytest.mark.asyncio
async def test_semantic_responsive_design_calls_llm():
    """6. Semantic responsive design/mobile-first -> LLM called with summary/project evidence."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["summary:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Mobile-first responsive UI in summary:1")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], summary="Experienced building mobile-first responsive web apps", experience=[], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["responsive design"], preferred_skills=[], skills=["responsive design"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert mock_evaluator.evaluate.call_count == 1
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_multiple_unresolved_batched_into_single_llm_call():
    """8. Multiple unresolved requirements (e.g. 4 requirements) -> exactly 1 batched LLM call."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id=f"skill:{i}", status=MatchStatus.MATCHED, confidence=0.90, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Valid")
        for i in range(1, 5)
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[{"description": "Developed role auth, token security, non-blocking APIs, and responsive layouts"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(
        required_skills=["authentication", "authorization", "asynchronous programming", "responsive design"],
        preferred_skills=[], skills=["authentication", "authorization", "asynchronous programming", "responsive design"],
        responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[],
    )

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert mock_evaluator.evaluate.call_count == 1
    assert len(verdicts) == 4
    call_args = mock_evaluator.evaluate.call_args[0]
    assert len(call_args[0]) == 4


@pytest.mark.asyncio
async def test_duplicate_requirement_no_duplicate_evaluation():
    """9. Duplicate requirements in JD -> deduplicated, no duplicate evaluation."""
    job = SimpleNamespace(
        required_skills=["React.js", "React.js", "Python", "Python"],
        preferred_skills=[], skills=["React.js", "Python"], responsibilities=[],
        degree_requirements=[], experience_requirements=[], certifications=[],
    )
    reqs = RequirementBuilder.build(job, config=None)
    assert len(reqs) == 2
    assert {r.text for r in reqs} == {"React.js", "Python"}


@pytest.mark.asyncio
async def test_groq_evaluator_cache_hit_avoids_llm_call(monkeypatch):
    """11. Identical candidate/JD payload -> instant cache hit with 0 additional HTTP calls."""
    evaluator = GroqMatchEvaluator()
    evaluator._cache.clear()

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented RBAC access control")]
    allowed = {"skill:1": {"experience:1"}}

    mock_client = MagicMock()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": '{"verdicts":[{"requirement_id":"skill:1","status":"MATCHED","confidence":0.95,"evidence_ids":["experience:1"],"reasoning":"RBAC satisfies authorization"}]}'
            }
        }]
    }
    mock_client.post = AsyncMock(return_value=mock_post_resp)
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda *args, **kwargs: mock_client)

    # Call 1: Misses cache, makes 1 HTTP call
    v1 = await evaluator.evaluate(reqs, evs, allowed)
    assert len(v1) == 1
    assert v1[0].status == MatchStatus.MATCHED
    assert mock_client.post.call_count == 1

    # Call 2: Hits cache, makes 0 HTTP calls
    v2 = await evaluator.evaluate(reqs, evs, allowed)
    assert len(v2) == 1
    assert v2[0].status == MatchStatus.MATCHED
    assert mock_client.post.call_count == 1
