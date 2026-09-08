import asyncio
import json
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

from app.core.config import get_settings
from app.services.llm.batch_pipeline import (
    PostDeterministicPipeline,
    GroqBatchExecutor,
    ResumeBatchContext,
    group_into_batches,
)
from app.services.matching_service import (
    Requirement,
    Evidence,
    RequirementKind,
    MatchStatus,
    MatchMethod,
    MatchVerdict,
    HybridMatchingService,
    EvidenceBuilder,
    RequirementBuilder,
    ProviderCircuitBreaker,
)


@pytest.fixture(autouse=True)
def mock_groq_settings():
    s = get_settings()
    orig_key = getattr(s, "GROQ_API_KEY", None)
    orig_enabled = getattr(s, "ENABLE_HYBRID_MATCHING", True)
    s.GROQ_API_KEY = "gsk_mock_test_key_for_pipeline"
    s.ENABLE_HYBRID_MATCHING = True
    ProviderCircuitBreaker.reset_breaker()
    yield s
    s.GROQ_API_KEY = orig_key
    s.ENABLE_HYBRID_MATCHING = orig_enabled
    ProviderCircuitBreaker.reset_breaker()



@pytest.fixture
def make_req():
    def _make(req_id: str, text: str, kind=RequirementKind.SKILL, required=True):
        return Requirement(
            requirement_id=req_id,
            text=text,
            kind=kind,
            required=required,
            importance="critical" if required else "important",
        )
    return _make


@pytest.fixture
def make_evidence():
    def _make(ev_id: str, text: str, kind="skills"):
        return Evidence(
            evidence_id=ev_id,
            text=text,
            kind=kind,
            confidence=1.0,
            date_range=None,
        )
    return _make


@pytest.fixture
def make_context(make_req, make_evidence):
    def _make(resume_id: str, req_ids: list[str] = None, ev_ids: list[str] = None):
        req_ids = req_ids or [f"{resume_id}_req_1"]
        ev_ids = ev_ids or [f"{resume_id}_ev_1"]
        reqs = [make_req(rid, f"Requirement {rid}") for rid in req_ids]
        evs = [make_evidence(eid, f"Evidence {eid}", kind="skills") for eid in ev_ids]
        allowed = {rid: {e.evidence_id for e in evs} for rid in req_ids}
        return ResumeBatchContext(
            resume_id=resume_id,
            requirements=reqs,
            candidate_evidence=evs,
            allowed_evidence=allowed,
        )
    return _make


# TEST 1: Exactly 3 eligible resumes -> 1 batch -> 1 Groq request
@pytest.mark.asyncio
async def test_three_resumes_one_batch_one_request(make_context):
    contexts = [make_context("res_1"), make_context("res_2"), make_context("res_3")]
    batches = group_into_batches(contexts, batch_size=3)
    assert len(batches) == 1
    assert len(batches[0]) == 3

    pipeline = PostDeterministicPipeline(max_concurrency=2, max_retries=2)
    mock_response = {
        "results": [
            {
                "resume_id": "res_1",
                "verdicts": [{"requirement_id": "res_1_req_1", "status": "MATCHED", "confidence": 0.95, "evidence_ids": ["res_1_ev_1"], "reasoning": "Direct match"}]
            },
            {
                "resume_id": "res_2",
                "verdicts": [{"requirement_id": "res_2_req_1", "status": "MATCHED", "confidence": 0.9, "evidence_ids": ["res_2_ev_1"], "reasoning": "Direct match"}]
            },
            {
                "resume_id": "res_3",
                "verdicts": [{"requirement_id": "res_3_req_1", "status": "MATCHED", "confidence": 0.85, "evidence_ids": ["res_3_ev_1"], "reasoning": "Direct match"}]
            }
        ]
    }

    with patch.object(pipeline.executor, "_call_groq_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps(mock_response)
        results = await pipeline.execute_parallel(contexts)

        assert mock_call.call_count == 1
        assert len(results) == 3
        assert "res_1" in results and "res_2" in results and "res_3" in results
        assert results["res_1"][0].status == MatchStatus.MATCHED


# TEST 2: 6 eligible resumes -> 2 batches of 3
@pytest.mark.asyncio
async def test_six_resumes_two_batches(make_context):
    contexts = [make_context(f"res_{i}") for i in range(1, 7)]
    batches = group_into_batches(contexts, batch_size=3)
    assert len(batches) == 2
    assert len(batches[0]) == 3
    assert len(batches[1]) == 3

    pipeline = PostDeterministicPipeline(max_concurrency=2, max_retries=2)

    async def fake_call(payload, timeout):
        res_ids = [f"res_{i}" for i in range(1, 7)]
        return json.dumps({
            "results": [
                {
                    "resume_id": rid,
                    "verdicts": [{"requirement_id": f"{rid}_req_1", "status": "MATCHED", "confidence": 0.9, "evidence_ids": [f"{rid}_ev_1"], "reasoning": "Match"}]
                }
                for rid in res_ids
            ]
        })

    with patch.object(pipeline.executor, "_call_groq_api", side_effect=fake_call) as mock_call:
        results = await pipeline.execute_parallel(contexts)
        assert mock_call.call_count == 2
        assert len(results) == 6


# TEST 3: 7 eligible resumes -> 3 batches (3, 3, 1)
@pytest.mark.asyncio
async def test_seven_resumes_three_batches(make_context):
    contexts = [make_context(f"res_{i}") for i in range(1, 8)]
    batches = group_into_batches(contexts, batch_size=3)
    assert len(batches) == 3
    assert len(batches[0]) == 3
    assert len(batches[1]) == 3
    assert len(batches[2]) == 1

    pipeline = PostDeterministicPipeline(max_concurrency=3, max_retries=2)

    async def fake_call(payload, timeout):
        res_ids = [f"res_{i}" for i in range(1, 8)]
        return json.dumps({
            "results": [
                {
                    "resume_id": rid,
                    "verdicts": [{"requirement_id": f"{rid}_req_1", "status": "MATCHED", "confidence": 0.9, "evidence_ids": [f"{rid}_ev_1"], "reasoning": "Match"}]
                }
                for rid in res_ids
            ]
        })

    with patch.object(pipeline.executor, "_call_groq_api", side_effect=fake_call) as mock_call:
        results = await pipeline.execute_parallel(contexts)
        assert mock_call.call_count == 3
        assert len(results) == 7


# TEST 4: Multiple batches execute concurrently in parallel
@pytest.mark.asyncio
async def test_parallel_batch_concurrency(make_context):
    contexts = [make_context(f"res_{i}") for i in range(1, 7)]
    pipeline = PostDeterministicPipeline(max_concurrency=2, max_retries=1)

    running_concurrent = 0
    max_observed_concurrent = 0

    async def fake_call(payload, timeout):
        nonlocal running_concurrent, max_observed_concurrent
        running_concurrent += 1
        max_observed_concurrent = max(max_observed_concurrent, running_concurrent)
        await asyncio.sleep(0.05)
        running_concurrent -= 1
        res_ids = [f"res_{i}" for i in range(1, 7)]
        return json.dumps({
            "results": [
                {
                    "resume_id": rid,
                    "verdicts": [{"requirement_id": f"{rid}_req_1", "status": "MATCHED", "confidence": 0.9, "evidence_ids": [f"{rid}_ev_1"], "reasoning": "Match"}]
                }
                for rid in res_ids
            ]
        })

    with patch.object(pipeline.executor, "_call_groq_api", side_effect=fake_call):
        results = await pipeline.execute_parallel(contexts)
        assert len(results) == 6
        assert max_observed_concurrent >= 2  # Executed concurrently in parallel


# TEST 5: Groq success -> no retry triggered
@pytest.mark.asyncio
async def test_groq_success_no_retry(make_context):
    contexts = [make_context("res_1"), make_context("res_2"), make_context("res_3")]
    pipeline = PostDeterministicPipeline(max_concurrency=1, max_retries=3)

    mock_resp = {
        "results": [
            {
                "resume_id": ctx.resume_id,
                "verdicts": [{"requirement_id": ctx.requirements[0].requirement_id, "status": "MATCHED", "confidence": 0.9, "evidence_ids": [ctx.candidate_evidence[0].evidence_id], "reasoning": "Match"}]
            }
            for ctx in contexts
        ]
    }

    with patch.object(pipeline.executor, "_call_groq_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps(mock_resp)
        results = await pipeline.execute_parallel(contexts)
        assert mock_call.call_count == 1
        assert len(results) == 3


# TEST 6: Groq timeout -> retries with Groq and succeeds on retry
@pytest.mark.asyncio
async def test_groq_timeout_retries_and_succeeds(make_context):
    contexts = [make_context("res_1"), make_context("res_2"), make_context("res_3")]
    pipeline = PostDeterministicPipeline(max_concurrency=1, max_retries=2)

    call_count = 0
    success_resp = {
        "results": [
            {
                "resume_id": ctx.resume_id,
                "verdicts": [{"requirement_id": ctx.requirements[0].requirement_id, "status": "MATCHED", "confidence": 0.9, "evidence_ids": [ctx.candidate_evidence[0].evidence_id], "reasoning": "Match"}]
            }
            for ctx in contexts
        ]
    }

    async def flaky_call(payload, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError("Groq request timed out after 30s")
        return json.dumps(success_resp)

    with patch.object(pipeline.executor, "_call_groq_api", side_effect=flaky_call):
        results = await pipeline.execute_parallel(contexts)
        assert call_count == 2
        assert len(results) == 3
        assert results["res_1"][0].status == MatchStatus.MATCHED


# TEST 7: Partial batch failure (resumes A & B succeed, C fails/missing) -> retry C only, preserve A & B
@pytest.mark.asyncio
async def test_partial_batch_failure_retries_only_missing_resumes(make_context):
    contexts = [make_context("res_A"), make_context("res_B"), make_context("res_C")]
    pipeline = PostDeterministicPipeline(max_concurrency=1, max_retries=2)

    call_history = []

    async def partial_call(payload, timeout):
        messages = payload.get("messages", [])
        prompt_text = messages[-1].get("content", "") if messages else ""
        cands_in_prompt = [cid for cid in ["res_A", "res_B", "res_C"] if cid in prompt_text]
        call_history.append(cands_in_prompt)

        if len(call_history) == 1:
            # First attempt: only returns res_A and res_B
            return json.dumps({
                "results": [
                    {
                        "resume_id": "res_A",
                        "verdicts": [{"requirement_id": "res_A_req_1", "status": "MATCHED", "confidence": 0.9, "evidence_ids": ["res_A_ev_1"], "reasoning": "A Match"}]
                    },
                    {
                        "resume_id": "res_B",
                        "verdicts": [{"requirement_id": "res_B_req_1", "status": "MATCHED", "confidence": 0.88, "evidence_ids": ["res_B_ev_1"], "reasoning": "B Match"}]
                    }
                ]
            })
        else:
            # Second attempt: retry contains res_C
            return json.dumps({
                "results": [
                    {
                        "resume_id": "res_C",
                        "verdicts": [{"requirement_id": "res_C_req_1", "status": "MATCHED", "confidence": 0.92, "evidence_ids": ["res_C_ev_1"], "reasoning": "C Match"}]
                    }
                ]
            })

    with patch.object(pipeline.executor, "_call_groq_api", side_effect=partial_call):
        results = await pipeline.execute_parallel(contexts)
        assert len(call_history) == 2
        # First call included all 3
        assert set(call_history[0]) == {"res_A", "res_B", "res_C"}
        # Second call retried ONLY res_C
        assert call_history[1] == ["res_C"]
        # All 3 have valid results
        assert len(results) == 3
        assert results["res_A"][0].status == MatchStatus.MATCHED
        assert results["res_B"][0].status == MatchStatus.MATCHED
        assert results["res_C"][0].status == MatchStatus.MATCHED


# TEST 8: Deterministic MATCHED -> zero Groq calls
@pytest.mark.asyncio
async def test_deterministic_matched_zero_groq_calls():
    job = SimpleNamespace(
        required_skills=["Python", "FastAPI"],
        optional_skills=[],
        responsibilities=[],
        requirements=[],
        degrees=[],
        certifications=[],
        languages=[],
        min_experience_months=0,
    )
    resume = SimpleNamespace(
        id="cand_1",
        candidate_name="Alice",
        skills=["Python", "FastAPI"],
        experience_entries=[],
        project_entries=[],
        degree_entries=[],
        certification_entries=[],
        language_entries=[],
    )
    extracted = SimpleNamespace(
        skills=["Python", "FastAPI"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    hybrid = HybridMatchingService()
    with patch.object(hybrid.post_pipeline, "execute_parallel", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = {}
        enriched, verdicts = await hybrid.match(job, resume, extracted)
        # Verify post_pipeline was NEVER called because all items were deterministically matched
        assert mock_post.call_count == 0
        assert all(v.status == MatchStatus.MATCHED for v in verdicts)
        assert all(v.method in {MatchMethod.EXACT, MatchMethod.ALIAS, MatchMethod.CONCEPT} for v in verdicts)


# TEST 9: Deterministic non-MATCHED + minimum meaningful evidence -> Groq call made
@pytest.mark.asyncio
async def test_deterministic_non_matched_with_evidence_calls_groq():
    job = SimpleNamespace(
        required_skills=["Kubernetes"],
        optional_skills=[],
        responsibilities=[],
        requirements=[],
        degrees=[],
        certifications=[],
        languages=[],
        min_experience_months=0,
    )
    resume = SimpleNamespace(
        id="cand_2",
        candidate_name="Bob",
        skills=["Docker"],  # Not Kubernetes, but provides contextual DevOps evidence
        experience_entries=[
            SimpleNamespace(
                title="DevOps Engineer",
                company="Acme Corp",
                responsibilities=["Orchestrated container clusters with container tooling"],
            )
        ],
        project_entries=[],
        degree_entries=[],
        certification_entries=[],
        language_entries=[],
    )
    extracted = SimpleNamespace(
        skills=["Docker"],
        experience=[
            SimpleNamespace(
                title="DevOps Engineer",
                company="Acme Corp",
                responsibilities=["Orchestrated container clusters with container tooling"],
            )
        ],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    hybrid = HybridMatchingService()
    reqs = RequirementBuilder.build(job, None)
    req_id = reqs[0].requirement_id

    # Mock post_pipeline.execute_parallel to return a matched verdict from LLM
    with patch.object(hybrid.post_pipeline, "execute_parallel", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = {
            "cand_2": [
                MatchVerdict(
                    requirement_id=req_id,
                    requirement_text="Kubernetes",
                    kind=RequirementKind.SKILL,
                    status=MatchStatus.MATCHED,
                    confidence=0.88,
                    evidence_ids=["experience:1"],
                    reasoning="Container orchestration experience covers Kubernetes",
                    method=MatchMethod.LLM_CONFIRMED,
                )
            ]
        }
        enriched, verdicts = await hybrid.match(job, resume, extracted)
        assert mock_post.call_count == 1
        assert verdicts[0].status == MatchStatus.MATCHED
        assert verdicts[0].method == MatchMethod.LLM_CONFIRMED


# TEST 10: Deterministic non-MATCHED + zero candidate evidence -> zero Groq calls
@pytest.mark.asyncio
async def test_deterministic_non_matched_zero_evidence_skips_groq():
    job = SimpleNamespace(
        required_skills=["Rust"],
        optional_skills=[],
        responsibilities=[],
        requirements=[],
        degrees=[],
        certifications=[],
        languages=[],
        min_experience_months=0,
    )
    resume = SimpleNamespace(
        id="cand_3",
        candidate_name="Charlie",
        skills=[],  # Completely empty
        experience_entries=[],
        project_entries=[],
        degree_entries=[],
        certification_entries=[],
        language_entries=[],
    )
    extracted = SimpleNamespace(
        skills=[],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    hybrid = HybridMatchingService()
    with patch.object(hybrid.post_pipeline, "execute_parallel", new_callable=AsyncMock) as mock_post:
        enriched, verdicts = await hybrid.match(job, resume, extracted)
        # Should NOT call Groq because there is 0 evidence to evaluate
        assert mock_post.call_count == 0
        assert verdicts[0].status == MatchStatus.NO_MATCH
        assert "No candidate evidence available" in verdicts[0].reasoning


# TEST 11: Invalid evidence ID cited in LLM response -> rejected
@pytest.mark.asyncio
async def test_invalid_evidence_id_rejected(make_context):
    ctx = make_context("res_1", req_ids=["req_1"], ev_ids=["ev_real"])
    pipeline = PostDeterministicPipeline(max_concurrency=1, max_retries=1)

    mock_resp = {
        "results": [
            {
                "resume_id": "res_1",
                "verdicts": [
                    {
                        "requirement_id": "req_1",
                        "status": "MATCHED",
                        "confidence": 0.9,
                        # ev_fake does NOT exist in candidate allowed evidence
                        "evidence_ids": ["ev_fake"],
                        "reasoning": "Fabricated match",
                    }
                ]
            }
        ]
    }

    with patch.object(pipeline.executor, "_call_groq_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps(mock_resp)
        results = await pipeline.execute_parallel([ctx])
        verdict = results["res_1"][0]
        # Invalid evidence must be stripped out
        assert "ev_fake" not in verdict.evidence_ids
        # Since status was MATCHED but had no valid evidence, status is corrected to UNRESOLVED/NO_MATCH
        assert verdict.status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


# TEST 12: Resume A evidence cannot satisfy Resume B requirement (cross-talk prevention)
@pytest.mark.asyncio
async def test_cross_candidate_evidence_isolation(make_context):
    ctx_A = make_context("res_A", req_ids=["req_A"], ev_ids=["ev_A"])
    ctx_B = make_context("res_B", req_ids=["req_B"], ev_ids=["ev_B"])
    pipeline = PostDeterministicPipeline(max_concurrency=1, max_retries=1)

    mock_resp = {
        "results": [
            {
                "resume_id": "res_B",
                "verdicts": [
                    {
                        "requirement_id": "req_B",
                        "status": "MATCHED",
                        "confidence": 0.9,
                        # Cross-talk: res_B cites res_A's evidence!
                        "evidence_ids": ["ev_A"],
                        "reasoning": "Citing other candidate evidence",
                    }
                ]
            },
            {
                "resume_id": "res_A",
                "verdicts": [
                    {
                        "requirement_id": "req_A",
                        "status": "MATCHED",
                        "confidence": 0.95,
                        "evidence_ids": ["ev_A"],
                        "reasoning": "Legitimate match",
                    }
                ]
            }
        ]
    }

    with patch.object(pipeline.executor, "_call_groq_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps(mock_resp)
        results = await pipeline.execute_parallel([ctx_A, ctx_B])
        # res_A receives its valid match
        assert results["res_A"][0].status == MatchStatus.MATCHED
        assert "ev_A" in results["res_A"][0].evidence_ids

        # res_B's cross-candidate citation is rejected
        assert "ev_A" not in results["res_B"][0].evidence_ids
        assert results["res_B"][0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


# TEST 13: Malformed Groq JSON response -> retry / proper failure handling
@pytest.mark.asyncio
async def test_malformed_groq_json_retried_or_failed(make_context):
    contexts = [make_context("res_1"), make_context("res_2")]
    pipeline = PostDeterministicPipeline(max_concurrency=1, max_retries=2)

    call_count = 0
    valid_resp = {
        "results": [
            {
                "resume_id": ctx.resume_id,
                "verdicts": [{"requirement_id": ctx.requirements[0].requirement_id, "status": "MATCHED", "confidence": 0.9, "evidence_ids": [ctx.candidate_evidence[0].evidence_id], "reasoning": "Match"}]
            }
            for ctx in contexts
        ]
    }

    async def malformed_then_success(payload, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Non-dict or malformed object
            return "This is not valid json dictionary"
        return json.dumps(valid_resp)

    with patch.object(pipeline.executor, "_call_groq_api", side_effect=malformed_then_success):
        results = await pipeline.execute_parallel(contexts)
        assert call_count == 2
        assert len(results) == 2
        assert results["res_1"][0].status == MatchStatus.MATCHED


# TEST 14: Successful result is never duplicated or overwritten during retries
@pytest.mark.asyncio
async def test_successful_result_not_duplicated(make_context):
    contexts = [make_context("res_1"), make_context("res_2"), make_context("res_3")]
    pipeline = PostDeterministicPipeline(max_concurrency=1, max_retries=2)

    call_count = 0
    async def partial_fail_then_complete(payload, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return json.dumps({
                "results": [
                    {
                        "resume_id": "res_1",
                        "verdicts": [{"requirement_id": "res_1_req_1", "status": "MATCHED", "confidence": 0.99, "evidence_ids": ["res_1_ev_1"], "reasoning": "Res 1 Success"}]
                    }
                ]
            })
        else:
            return json.dumps({
                "results": [
                    {
                        "resume_id": "res_2",
                        "verdicts": [{"requirement_id": "res_2_req_1", "status": "MATCHED", "confidence": 0.95, "evidence_ids": ["res_2_ev_1"], "reasoning": "Res 2 Success"}]
                    },
                    {
                        "resume_id": "res_3",
                        "verdicts": [{"requirement_id": "res_3_req_1", "status": "MATCHED", "confidence": 0.92, "evidence_ids": ["res_3_ev_1"], "reasoning": "Res 3 Success"}]
                    }
                ]
            })

    with patch.object(pipeline.executor, "_call_groq_api", side_effect=partial_fail_then_complete):
        results = await pipeline.execute_parallel(contexts)
        assert len(results) == 3
        # Ensure res_1 has exactly 1 verdict and kept its original confidence 0.99
        assert len(results["res_1"]) == 1
        assert results["res_1"][0].confidence == 0.99
