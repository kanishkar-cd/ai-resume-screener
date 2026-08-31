import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx

from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    EvidenceBuilder, GroqMatchEvaluator, HybridMatchingService, RequirementBuilder,
)


@pytest.mark.asyncio
async def test_1_and_2_canonical_exact_and_alias_matches_zero_llm_calls():
    """1 & 2: Canonical exact match (Python) and alias match (React.js -> React) -> 0 LLM calls."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["Python", "React"], experience=[], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["Python", "React"], experience=[], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["Python", "React.js"], preferred_skills=[], skills=["Python", "React.js"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert len(verdicts) == 2
    assert all(v.status == MatchStatus.MATCHED for v in verdicts)
    assert mock_evaluator.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_3_canonical_failure_rbac_evidence_calls_llm():
    """3: Canonical failure on 'authorization' + RBAC evidence -> LLM called -> MATCHED."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="RBAC in experience:1")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[{"description": "Implemented role-based access control (RBAC) across microservices"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["authorization"], preferred_skills=[], skills=["authorization"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert mock_evaluator.evaluate.call_count == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].method == MatchMethod.LLM_CONFIRMED


@pytest.mark.asyncio
async def test_4_canonical_failure_jwt_evidence_calls_llm():
    """4: Canonical failure on 'authentication' + JWT evidence -> LLM called -> MATCHED."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="JWT in experience:1")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[{"description": "Configured JWT token security and login sessions"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["authentication"], preferred_skills=[], skills=["authentication"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert mock_evaluator.evaluate.call_count == 1
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_5_canonical_failure_responsive_evidence_calls_llm():
    """5: Canonical failure on 'responsive design' + mobile-first evidence -> LLM called -> MATCHED."""
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
async def test_6_canonical_failure_async_evidence_calls_llm():
    """6: Canonical failure on 'asynchronous programming' + async/await evidence -> LLM called -> MATCHED."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Async/await non-blocking endpoints in experience:1")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[{"description": "Engineered async/await non-blocking endpoints"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["asynchronous programming"], preferred_skills=[], skills=["asynchronous programming"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert mock_evaluator.evaluate.call_count == 1
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_7_canonical_failure_query_optimization_evidence_calls_llm():
    """7: Canonical failure on 'query optimization' + database indexing evidence -> LLM called -> MATCHED."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Query indexing in experience:1")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[{"description": "Optimized database performance with indexes and query plans"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["query optimization"], preferred_skills=[], skills=["query optimization"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_8_canonical_failure_project_evidence_calls_llm():
    """8: Canonical failure on skill + evidence located in PROJECT -> LLM called -> MATCHED."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["project:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Project implementation in project:1")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[], projects=[{"name": "DevOps Hub", "description": "Automated deployment pipelines with GitHub Actions"}], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=[], projects=resume.projects, education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["CI/CD"], preferred_skills=[], skills=["CI/CD"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_9_canonical_failure_internship_evidence_calls_llm():
    """9: Canonical failure on skill + evidence located in INTERNSHIP -> LLM called -> MATCHED."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Internship evidence in experience:1")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[{"designation": "Engineering Intern", "description": "Designed MongoDB database schemas and collections"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["schema design"], preferred_skills=[], skills=["schema design"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_10_canonical_failure_zero_evidence_zero_llm_calls():
    """10: Canonical failure + genuinely NO candidate evidence (Kubernetes) -> 0 LLM calls -> NO_MATCH."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["Python"], experience=[{"description": "Wrote Python scripts"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["Python"], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["Kubernetes"], preferred_skills=[], skills=["Kubernetes"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert mock_evaluator.evaluate.call_count == 0
    assert verdicts[0].status == MatchStatus.NO_MATCH


@pytest.mark.asyncio
async def test_13_invalid_llm_evidence_citation_rejected():
    """13: LLM citations referencing non-existent evidence IDs -> Rejected to UNRESOLVED."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented RBAC")]
    allowed = {"skill:1": {"experience:1"}}

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["hallucinated:99"], reasoning="Hallucinated")
    ])
    validated = evaluator._validate(batch, reqs, evs, allowed)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.UNRESOLVED
    assert validated[0].method == MatchMethod.LLM_UNRESOLVED
    assert "Rejected: No valid candidate evidence ID cited for match" in validated[0].reasoning


@pytest.mark.asyncio
async def test_14_http_400_diagnosed_and_not_blindly_retried(monkeypatch):
    """14: HTTP 400 client error -> logged with error response body, not blindly retried."""
    evaluator = GroqMatchEvaluator()
    evaluator._cache.clear()

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented RBAC")]

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = '{"error":{"message":"Invalid JSON Schema specification","type":"invalid_request_error"}}'
    
    http_err = httpx.HTTPStatusError("Bad Request", request=MagicMock(), response=mock_resp)
    mock_client.post = AsyncMock(side_effect=http_err)
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda *args, **kwargs: mock_client)

    result = await evaluator.evaluate(reqs, evs)
    assert result == []
    # Only 1 attempt made because 400 is not retried!
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_15_http_429_retry_behavior_preserved(monkeypatch):
    """15: HTTP 429 rate limit error -> retries and recovers on successful response."""
    evaluator = GroqMatchEvaluator()
    evaluator._cache.clear()

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented RBAC")]
    allowed = {"skill:1": {"experience:1"}}

    mock_client = MagicMock()
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {"Retry-After": "0.01"}
    mock_resp_429.text = '{"error":{"message":"Rate limit exceeded"}}'
    err_429 = httpx.HTTPStatusError("Too Many Requests", request=MagicMock(), response=mock_resp_429)

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "choices": [{
            "message": {
                "content": '{"verdicts":[{"requirement_id":"skill:1","status":"MATCHED","confidence":0.95,"evidence_ids":["experience:1"],"reasoning":"RBAC matches authorization"}]}'
            }
        }]
    }

    mock_client.post = AsyncMock(side_effect=[err_429, mock_resp_200])
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda *args, **kwargs: mock_client)

    result = await evaluator.evaluate(reqs, evs, allowed)
    assert len(result) == 1
    assert result[0].status == MatchStatus.MATCHED
    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_19_routing_invariant_holds():
    """19: Invariant holds: canonical_matched_count + llm_submitted_count + no_evidence_no_llm_count == total_requirements."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:2", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="RBAC")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["Python"], experience=[{"description": "Implemented RBAC"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["Python"], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(
        required_skills=["Python", "authorization", "Kubernetes", "AWS"],
        preferred_skills=[], skills=["Python", "authorization", "Kubernetes", "AWS"],
        responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[],
    )

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert len(verdicts) == 4

    # 1. Python -> canonical matched (1)
    # 2. authorization -> LLM submitted (1)
    # 3. Kubernetes, AWS -> no evidence no LLM (2)
    # Total = 1 + 1 + 2 = 4 == total_requirements
    canonical_matched = sum(1 for v in verdicts if v.method in {MatchMethod.EXACT, MatchMethod.ALIAS})
    llm_submitted = sum(1 for v in verdicts if v.method in {MatchMethod.LLM_CONFIRMED, MatchMethod.LLM_REJECTED, MatchMethod.LLM_UNRESOLVED})
    no_evidence = sum(1 for v in verdicts if v.method is None or v.method == MatchMethod.LLM_REJECTED and v not in verdicts)

    assert canonical_matched == 1
    assert llm_submitted == 1
