import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.core.config import Settings, get_settings
from app.schemas.matching import (
    Evidence,
    MatchMethod,
    MatchStatus,
    MatchVerdict,
    Requirement,
    RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher,
    EvidenceBuilder,
    GroqKeyEntry,
    GroqKeyPoolManager,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    HybridMatchingService,
    ProviderCircuitBreaker,
    RequirementBuilder,
    SmartMatchEvaluator,
)


def make_test_settings():
    return MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY_1="mock_groq_key_1",
        GROQ_API_KEY_2="mock_groq_key_2",
        GROQ_API_KEY_3="mock_groq_key_3",
        GROQ_API_KEY="mock_groq_key_1",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.10,
        GROQ_MAX_RETRIES=2,
        GROQ_TOKEN_BUDGET_PER_RESUME=7000,
        GROQ_MAX_COMPLETION_TOKENS=3500,
        GROQ_ESTIMATED_OUTPUT_TOKENS=350,
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        CEREBRAS_MAX_RETRIES=1,
        CEREBRAS_TPM_LIMIT=60000,
        CEREBRAS_TPM_SAFETY_MARGIN=0.10,
        MAX_CONCURRENT_RESUMES=3,
        LLM_BATCH_THROTTLE_SECONDS=0.0,
        LLM_BATCH_CHUNK_SIZE=20,
        PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS=60.0,
        PROVIDER_CIRCUIT_BREAKER_MAX_FAILURES=2,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_KEYWORD_OVERLAP_THRESHOLD=0.15,
        HYBRID_MATCHING_MAX_EVIDENCE_PER_REQUIREMENT=5,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )


def make_verdict_item(req_id: str, coverage: float = 1.0, evidence_ids: list[str] | None = None) -> dict:
    return {
        "requirement_id": req_id,
        "status": "MATCHED",
        "confidence": 0.95,
        "sub_claims": [f"claim for {req_id}"],
        "sub_claim_evidence": [
            {"claim": f"claim for {req_id}", "evidence_level": "direct", "note": "Demonstrated"}
        ],
        "coverage_score": coverage,
        "importance": "critical",
        "evidence_ids": evidence_ids or ["ev1", "e1", "e2", "e3", "ev_a", "ev_b", "skills:1", "experience:1", "skill:1", "skill:2", "skill:3"],
        "reasoning": f"Evidence directly demonstrates {req_id}",
    }


def make_mock_http_response(req_ids: list[str]) -> MagicMock:
    verdicts = [make_verdict_item(rid) for rid in req_ids]
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "chatcmpl-mock-id",
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"verdicts": verdicts})}}],
        "usage": {"prompt_tokens": 500, "completion_tokens": 300, "total_tokens": 800},
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


@pytest.fixture(autouse=True)
def reset_pool_state():
    settings = make_test_settings()
    pool = GroqKeyPoolManager.get_manager(settings)
    pool._load_keys()
    GroqMatchEvaluator._cache.clear()
    ProviderCircuitBreaker.reset_breaker()
    GroqTokenBudgetGate.reset_gate()


# ==============================================================================
# TEST 1 — ONE RESUME
# ==============================================================================
@pytest.mark.asyncio
async def test_1_one_resume_single_groq_call_zero_cerebras():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)
    cerebras_spy = AsyncMock()
    evaluator.cerebras = cerebras_spy

    reqs = [Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True)]
    evs = [Evidence(evidence_id="ev1", kind="skills", text="Python Dev", canonical_terms=["python"])]

    called_keys = []

    async def mock_post(url, headers=None, json=None, timeout=None):
        auth_header = headers.get("Authorization", "")
        called_keys.append(auth_header)
        return make_mock_http_response(["req_1"])

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        verdicts, telemetry = await evaluator.evaluate(reqs, evs, resume_id="resume_1")

        assert len(verdicts) == 1
        assert verdicts[0].status == MatchStatus.MATCHED
        assert len(called_keys) == 1
        assert "Bearer mock_groq_key_1" in called_keys[0]
        assert cerebras_spy.call_count == 0
        assert telemetry["provider_selected"] == "groq"
        assert telemetry["token_budget"] == 7000


# ==============================================================================
# TEST 2 — TWO RESUMES
# ==============================================================================
@pytest.mark.asyncio
async def test_2_two_resumes_independent_keys_zero_cerebras():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)

    reqs_a = [Requirement(requirement_id="req_a", kind=RequirementKind.SKILL, text="Python", required=True)]
    evs_a = [Evidence(evidence_id="ev_a", kind="skills", text="Python Dev", canonical_terms=["python"])]

    reqs_b = [Requirement(requirement_id="req_b", kind=RequirementKind.SKILL, text="FastAPI", required=True)]
    evs_b = [Evidence(evidence_id="ev_b", kind="skills", text="FastAPI Dev", canonical_terms=["fastapi"])]

    called_keys = []

    async def mock_post(url, headers=None, json=None, timeout=None):
        auth_header = headers.get("Authorization", "")
        called_keys.append(auth_header)
        data = json if isinstance(json, dict) else {}
        req_ids = [r["requirement_id"] for r in __import__("json").loads(data["messages"][1]["content"])["requirements"]]
        await asyncio.sleep(0.01)
        return make_mock_http_response(req_ids)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        res_a, res_b = await asyncio.gather(
            evaluator.evaluate(reqs_a, evs_a, resume_id="resume_A"),
            evaluator.evaluate(reqs_b, evs_b, resume_id="resume_B"),
        )

        assert len(res_a[0]) == 1
        assert len(res_b[0]) == 1
        assert len(called_keys) == 2
        keys_set = set(called_keys)
        assert len(keys_set) == 2
        assert "Bearer mock_groq_key_1" in keys_set
        assert "Bearer mock_groq_key_2" in keys_set


# ==============================================================================
# TEST 3 — THREE RESUMES
# ==============================================================================
@pytest.mark.asyncio
async def test_3_three_resumes_all_three_keys_allocated_safely():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)

    called_keys = []

    async def mock_post(url, headers=None, json=None, timeout=None):
        auth_header = headers.get("Authorization", "")
        called_keys.append(auth_header)
        data = json if isinstance(json, dict) else {}
        req_ids = [r["requirement_id"] for r in __import__("json").loads(data["messages"][1]["content"])["requirements"]]
        await asyncio.sleep(0.01)
        return make_mock_http_response(req_ids)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        res_a, res_b, res_c = await asyncio.gather(
            evaluator.evaluate([Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True)], [Evidence(evidence_id="e1", kind="skills", text="Python", canonical_terms=["python"])], resume_id="resume_1"),
            evaluator.evaluate([Requirement(requirement_id="req_2", kind=RequirementKind.SKILL, text="Docker", required=True)], [Evidence(evidence_id="e2", kind="skills", text="Docker", canonical_terms=["docker"])], resume_id="resume_2"),
            evaluator.evaluate([Requirement(requirement_id="req_3", kind=RequirementKind.SKILL, text="AWS", required=True)], [Evidence(evidence_id="e3", kind="skills", text="AWS", canonical_terms=["aws"])], resume_id="resume_3"),
        )

        assert len(res_a[0]) == 1
        assert len(res_b[0]) == 1
        assert len(res_c[0]) == 1
        assert len(called_keys) == 3
        assert set(called_keys) == {
            "Bearer mock_groq_key_1",
            "Bearer mock_groq_key_2",
            "Bearer mock_groq_key_3",
        }


# ==============================================================================
# TEST 4 — REQUEST ISOLATION
# ==============================================================================
@pytest.mark.asyncio
async def test_4_request_isolation_no_cross_resume_data():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)

    payloads_captured = {}

    async def mock_post(url, headers=None, json=None, timeout=None):
        content = __import__("json").loads(json["messages"][1]["content"])
        req_id = content["requirements"][0]["requirement_id"]
        payloads_captured[req_id] = content
        return make_mock_http_response([req_id])

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    req_a = [Requirement(requirement_id="req_alpha", kind=RequirementKind.SKILL, text="AlphaSkill", required=True)]
    ev_a = [Evidence(evidence_id="ev_alpha", kind="skills", text="Alpha Candidate Evidence", canonical_terms=["alpha"])]

    req_b = [Requirement(requirement_id="req_beta", kind=RequirementKind.SKILL, text="BetaSkill", required=True)]
    ev_b = [Evidence(evidence_id="ev_beta", kind="skills", text="Beta Candidate Evidence", canonical_terms=["beta"])]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        await asyncio.gather(
            evaluator.evaluate(req_a, ev_a, resume_id="resume_A"),
            evaluator.evaluate(req_b, ev_b, resume_id="resume_B"),
        )

        assert "req_alpha" in payloads_captured
        assert "req_beta" in payloads_captured

        alpha_content = payloads_captured["req_alpha"]
        beta_content = payloads_captured["req_beta"]

        assert any(e["evidence_id"] == "ev_alpha" for e in alpha_content["candidate_evidence"])
        assert not any(e["evidence_id"] == "ev_beta" for e in alpha_content["candidate_evidence"])

        assert any(e["evidence_id"] == "ev_beta" for e in beta_content["candidate_evidence"])
        assert not any(e["evidence_id"] == "ev_alpha" for e in beta_content["candidate_evidence"])


# ==============================================================================
# TEST 5 — KEY 1 429 ROTATION
# ==============================================================================
@pytest.mark.asyncio
async def test_5_key_1_429_rotates_to_key_2_success():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)

    attempt_keys = []

    resp_429 = MagicMock(spec=httpx.Response)
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "5"}
    err_429 = httpx.HTTPStatusError("429 Too Many Requests", request=MagicMock(), response=resp_429)

    async def mock_post(url, headers=None, json=None, timeout=None):
        auth = headers.get("Authorization", "")
        attempt_keys.append(auth)
        if "mock_groq_key_1" in auth:
            raise err_429
        return make_mock_http_response(["req_1"])

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        verdicts, telemetry = await evaluator.evaluate(
            [Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True)],
            [Evidence(evidence_id="e1", kind="skills", text="Python", canonical_terms=["python"])],
            resume_id="resume_1",
        )

        assert len(verdicts) == 1
        assert verdicts[0].status == MatchStatus.MATCHED
        assert len(attempt_keys) == 2
        assert "mock_groq_key_1" in attempt_keys[0]
        assert "mock_groq_key_2" in attempt_keys[1]
        assert telemetry["provider_selected"] == "groq"


# ==============================================================================
# TEST 6 — KEY 1 FAILURE LEAVES KEY 2 & 3 AVAILABLE
# ==============================================================================
@pytest.mark.asyncio
async def test_6_key_1_failure_keeps_key_2_and_3_available():
    settings = make_test_settings()
    pool = GroqKeyPoolManager.get_manager(settings)
    evaluator = SmartMatchEvaluator(settings)

    k1 = pool.keys[0]
    k1.record_failure(1000, status_code=500, is_permanent=True, error_msg="Server crash")

    assert not k1.is_available()
    assert pool.keys[1].is_available()
    assert pool.keys[2].is_available()

    called_keys = []

    async def mock_post(url, headers=None, json=None, timeout=None):
        called_keys.append(headers.get("Authorization", ""))
        return make_mock_http_response(["req_2"])

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        verdicts, _ = await evaluator.evaluate(
            [Requirement(requirement_id="req_2", kind=RequirementKind.SKILL, text="Go", required=True)],
            [Evidence(evidence_id="e2", kind="skills", text="Go", canonical_terms=["go"])],
            resume_id="resume_2",
        )

        assert len(verdicts) == 1
        assert "mock_groq_key_2" in called_keys[0]


# ==============================================================================
# TEST 7 — ALL 3 KEYS FAIL -> EVALUATION_FAILED, NO CEREBRAS
# ==============================================================================
@pytest.mark.asyncio
async def test_7_all_keys_fail_results_in_evaluation_failed_and_zero_cerebras():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)

    err_500 = httpx.HTTPStatusError("500 Server Error", request=MagicMock(), response=MagicMock(status_code=500))

    async def mock_post(url, headers=None, json=None, timeout=None):
        raise err_500

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        verdicts, telemetry = await evaluator.evaluate(
            [Requirement(requirement_id="req_fail", kind=RequirementKind.SKILL, text="Kubernetes", required=True)],
            [Evidence(evidence_id="e_fail", kind="skills", text="Kubernetes", canonical_terms=["k8s"])],
            resume_id="resume_fail",
        )

        assert len(verdicts) == 0
        assert telemetry["provider_selected"] == "none"


# ==============================================================================
# TEST 8 — 7,000 TOKEN BUDGET PER RESUME ENFORCEMENT
# ==============================================================================
def test_8_token_budget_per_resume_enforcement():
    settings = make_test_settings()
    pool = GroqKeyPoolManager.get_manager(settings)

    huge_reqs = [
        {"requirement_id": f"req_{i}", "text": "Very long requirement description " * 50}
        for i in range(50)
    ]
    huge_evs = [
        {"evidence_id": f"ev_{i}", "text": "Extensive candidate work history " * 50}
        for i in range(50)
    ]
    huge_payload = {
        "messages": [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": json.dumps({"requirements": huge_reqs, "candidate_evidence": huge_evs})},
        ]
    }

    est = pool.estimate_tokens(huge_payload)
    assert est <= 7000
    assert est > 0


# ==============================================================================
# TEST 9 — CONCURRENT RACE CONDITION SAFETY
# ==============================================================================
@pytest.mark.asyncio
async def test_9_concurrent_key_allocation_race_condition_safe():
    settings = make_test_settings()
    pool = GroqKeyPoolManager.get_manager(settings)

    results = await asyncio.gather(
        pool.acquire_key(2000),
        pool.acquire_key(2000),
        pool.acquire_key(2000),
    )

    allocated_ids = [k.key_id for k in results if k is not None]
    assert len(allocated_ids) == 3
    assert set(allocated_ids) == {"groq_key_1", "groq_key_2", "groq_key_3"}


# ==============================================================================
# TEST 10 — KEY ROTATION DURING CONCURRENT PROCESSING
# ==============================================================================
@pytest.mark.asyncio
async def test_10_concurrent_key_rotation_isolation():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)

    async def mock_post(url, headers=None, json=None, timeout=None):
        auth = headers.get("Authorization", "")
        data = json if isinstance(json, dict) else {}
        req_ids = [r["requirement_id"] for r in __import__("json").loads(data["messages"][1]["content"])["requirements"]]

        if "mock_groq_key_1" in auth:
            resp_429 = MagicMock(spec=httpx.Response)
            resp_429.status_code = 429
            resp_429.headers = {"Retry-After": "2"}
            raise httpx.HTTPStatusError("429 Rate Limit", request=MagicMock(), response=resp_429)

        await asyncio.sleep(0.01)
        return make_mock_http_response(req_ids)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        res1, res2, res3 = await asyncio.gather(
            evaluator.evaluate([Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True)], [Evidence(evidence_id="e1", kind="skills", text="Python", canonical_terms=["python"])], resume_id="resume_1"),
            evaluator.evaluate([Requirement(requirement_id="req_2", kind=RequirementKind.SKILL, text="Docker", required=True)], [Evidence(evidence_id="e2", kind="skills", text="Docker", canonical_terms=["docker"])], resume_id="resume_2"),
            evaluator.evaluate([Requirement(requirement_id="req_3", kind=RequirementKind.SKILL, text="AWS", required=True)], [Evidence(evidence_id="e3", kind="skills", text="AWS", canonical_terms=["aws"])], resume_id="resume_3"),
        )

        assert len(res1[0]) == 1
        assert len(res2[0]) == 1
        assert len(res3[0]) == 1
        assert res1[0][0].requirement_id == "req_1"
        assert res2[0][0].requirement_id == "req_2"
        assert res3[0][0].requirement_id == "req_3"


# ==============================================================================
# TEST 11 — PRESERVATION OF DETERMINISTIC MATCHING
# ==============================================================================
@pytest.mark.asyncio
async def test_11_deterministic_matching_preserved_on_groq_failure():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)

    job = SimpleNamespace(
        title="Software Engineer",
        required_skills=["Python", "FastAPI", "UnmatchedSkill"],
        preferred_skills=[],
        skills=["Python", "FastAPI", "UnmatchedSkill"],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )
    resume = SimpleNamespace(
        name="Candidate Test",
        skills=["Python", "FastAPI"],
        experience=[{"description": "Experienced developer"}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )
    extracted = SimpleNamespace(
        skills=["Python", "FastAPI"],
        experience=[{"description": "Experienced developer"}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    err = httpx.ConnectError("Network unreachable")
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = err

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        service = HybridMatchingService(settings=settings, evaluator=evaluator)
        _, verdicts = await service.match(job, resume, extracted)

        matched = [v for v in verdicts if v.status == MatchStatus.MATCHED]
        assert len(matched) == 2
        matched_skills = {v.requirement_text for v in matched}
        assert "Python" in matched_skills
        assert "FastAPI" in matched_skills

        failed = [v for v in verdicts if v.status == MatchStatus.EVALUATION_FAILED]
        assert len(failed) == 1
        assert failed[0].requirement_text == "UnmatchedSkill"


# ==============================================================================
# TEST 12 — END-TO-END SCORING WITH 3 RESUMES
# ==============================================================================
@pytest.mark.asyncio
async def test_12_end_to_end_scoring_three_resumes_zero_cerebras():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)
    service = HybridMatchingService(settings=settings, evaluator=evaluator)

    job = SimpleNamespace(
        title="Full Stack Engineer",
        required_skills=["Python", "React", "Docker"],
        preferred_skills=[],
        skills=["Python", "React", "Docker"],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )

    resumes_data = [
        SimpleNamespace(name="Cand 1", skills=["Python"], experience=[{"description": "Built React webapps"}]),
        SimpleNamespace(name="Cand 2", skills=["React"], experience=[{"description": "Docker container specialist"}]),
        SimpleNamespace(name="Cand 3", skills=["Docker"], experience=[{"description": "Python scripting guru"}]),
    ]

    async def mock_post(url, headers=None, json=None, timeout=None):
        data = json if isinstance(json, dict) else {}
        req_ids = [r["requirement_id"] for r in __import__("json").loads(data["messages"][1]["content"])["requirements"]]
        return make_mock_http_response(req_ids)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        results = await asyncio.gather(*[
            service.match(job, r, SimpleNamespace(skills=r.skills, experience=r.experience, projects=[], education=[], certifications=[], languages=[]))
            for r in resumes_data
        ])

        assert len(results) == 3
        for _, verdicts in results:
            assert len(verdicts) == 3
            assert all(v.status == MatchStatus.MATCHED for v in verdicts)


# ==============================================================================
# TEST 13 — 30+ UNRESOLVED REQUIREMENTS FIT IN 1 COMPACT GROQ REQUEST
# ==============================================================================
@pytest.mark.asyncio
async def test_13_large_batch_30_requirements_single_compact_request_zero_subbatches():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)
    service = HybridMatchingService(settings=settings, evaluator=evaluator)

    # 32 total requirements: 2 deterministic MATCHED, 30 LLM-eligible
    req_skills = [f"EnterpriseSpec_{i:02d}" for i in range(1, 33)]
    job = SimpleNamespace(
        title="Senior Architect",
        required_skills=req_skills,
        preferred_skills=[],
        skills=req_skills,
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )

    # Resume has exact match for first 2 requirements in skills, and experience evidence for candidate
    resume_skills = [
        "EnterpriseSpec_01",
        "EnterpriseSpec_02",
    ]
    exp_text = "Senior engineering experience across distributed systems and cloud infrastructure with EnterpriseSpec competencies."
    resume_data = SimpleNamespace(
        name="Candidate 30Req",
        skills=resume_skills,
        experience=[{"description": exp_text}],
    )
    extracted = SimpleNamespace(
        skills=resume_skills,
        experience=[{"description": exp_text}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    post_calls = []

    async def mock_post(url, headers=None, json=None, timeout=None):
        post_calls.append(json)
        data = json if isinstance(json, dict) else {}
        user_msg = __import__("json").loads(data["messages"][1]["content"])
        reqs_in_call = user_msg["requirements"]
        # Return compact verdicts
        compact_verdicts = [
            {"id": r["id"], "s": "MATCHED", "c": 0.95, "cov": 1.0, "e": ["experience:1"]}
            for r in reqs_in_call
        ]
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "chatcmpl-large-batch-1",
            "choices": [{"finish_reason": "stop", "message": {"content": __import__("json").dumps({"verdicts": compact_verdicts})}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 900, "total_tokens": 2100},
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        _, verdicts = await service.match(job, resume_data, extracted)

        # 1. Exactly 32 verdicts returned
        assert len(verdicts) == 32

        # 2. Exactly ONE physical HTTP Groq request made (ZERO sub-batch requests)
        assert len(post_calls) == 1

        # 3. Exactly 30 requirements were sent to Groq
        sent_reqs = __import__("json").loads(post_calls[0]["messages"][1]["content"])["requirements"]
        assert len(sent_reqs) == 30

        # 4. Zero EVALUATION_FAILED verdicts
        failed_verdicts = [v for v in verdicts if v.status == MatchStatus.EVALUATION_FAILED]
        assert len(failed_verdicts) == 0

        # 5. Deterministic matches remained untouched
        skill_1_verdict = next(v for v in verdicts if v.requirement_text == req_skills[0])
        skill_2_verdict = next(v for v in verdicts if v.requirement_text == req_skills[1])
        assert skill_1_verdict.status == MatchStatus.MATCHED
        assert skill_1_verdict.method == MatchMethod.EXACT
        assert skill_2_verdict.status == MatchStatus.MATCHED
        assert skill_2_verdict.method == MatchMethod.EXACT

        # 6. All LLM-evaluated requirements are MATCHED
        assert all(v.status == MatchStatus.MATCHED for v in verdicts)


# ==============================================================================
# TEST 14 — FINISH_REASON=LENGTH RESULTS IN NO SUB-BATCH RETRY
# ==============================================================================
@pytest.mark.asyncio
async def test_14_truncated_response_length_finish_reason_no_subbatch_retry():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)
    service = HybridMatchingService(settings=settings, evaluator=evaluator)

    req_skills = [f"Req_{i}" for i in range(1, 11)]  # 10 requirements
    job = SimpleNamespace(
        title="Dev",
        required_skills=req_skills,
        preferred_skills=[],
        skills=req_skills,
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )

    exp_text = " ".join([f"Worked with Req_{i}." for i in range(1, 11)])
    resume_data = SimpleNamespace(
        name="Candidate Truncated",
        skills=[],
        experience=[{"description": exp_text}],
    )
    extracted = SimpleNamespace(
        skills=[],
        experience=[{"description": exp_text}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    post_call_count = 0

    async def mock_post(url, headers=None, json=None, timeout=None):
        nonlocal post_call_count
        post_call_count += 1
        # Return only 4 verdicts out of 10 with finish_reason="length"
        compact_verdicts = [
            {"id": f"skill:{i}", "s": "MATCHED", "c": 0.95, "cov": 1.0, "e": ["experience:1"]}
            for i in range(1, 5)
        ]
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "chatcmpl-truncated",
            "choices": [{"finish_reason": "length", "message": {"content": __import__("json").dumps({"verdicts": compact_verdicts})}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 400, "total_tokens": 900},
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        _, verdicts = await service.match(job, resume_data, extracted)

        # 1. Exactly ONE physical HTTP request made — NO sub-batch retry
        assert post_call_count == 1

        # 2. Total 10 verdicts returned
        assert len(verdicts) == 10

        # 3. 4 parsed verdicts succeeded
        matched = [v for v in verdicts if v.status == MatchStatus.MATCHED]
        assert len(matched) == 4

        # 4. 6 missing verdicts cleanly marked EVALUATION_FAILED (never silently NO_MATCH)
        failed = [v for v in verdicts if v.status == MatchStatus.EVALUATION_FAILED]
        assert len(failed) == 6


# ==============================================================================
# TEST 15 — HTTP 400 BAD REQUEST NEVER ROTATES KEYS (EXACTLY 1 ATTEMPT)
# ==============================================================================
@pytest.mark.asyncio
async def test_15_http_400_bad_request_no_key_rotation_single_attempt():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)
    service = HybridMatchingService(settings=settings, evaluator=evaluator)

    job = SimpleNamespace(
        title="Full Stack Dev",
        required_skills=["Python", "Kafka", "Docker"],
        preferred_skills=[],
        skills=["Python", "Kafka", "Docker"],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )

    resume_data = SimpleNamespace(
        name="Candidate 400",
        skills=["Python"],  # Deterministic exact match
        experience=[{"description": "Built event-driven microservices with Kafka and Docker."}],
    )
    extracted = SimpleNamespace(
        skills=["Python"],
        experience=[{"description": "Built event-driven microservices with Kafka and Docker."}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    post_call_count = 0
    pool = GroqKeyPoolManager.get_manager(settings)
    initial_circuits = {k.key_id: k.circuit_state for k in pool.keys}

    # Simulate HTTP 400 Bad Request error response from Groq
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "error": {
            "message": "The model `openai/gpt-oss-20b` does not exist or you do not have access to it.",
            "type": "invalid_request_error",
            "code": "model_not_found",
        }
    }
    mock_resp.text = '{"error": {"message": "The model `openai/gpt-oss-20b` does not exist", "type": "invalid_request_error", "code": "model_not_found"}}'
    err_400 = httpx.HTTPStatusError("Client error '400 Bad Request'", request=MagicMock(), response=mock_resp)

    async def mock_post(url, headers=None, json=None, timeout=None):
        nonlocal post_call_count
        post_call_count += 1
        raise err_400

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        _, verdicts = await service.match(job, resume_data, extracted)

        # 1. Exactly ONE physical HTTP request made — NO rotation to other keys
        assert post_call_count == 1

        # 2. Key 1 circuit state remained CLOSED (not marked permanently unavailable)
        for k in pool.keys:
            assert k.circuit_state == "CLOSED"

        # 3. Deterministic match (Python) preserved intact
        python_verdict = next(v for v in verdicts if v.requirement_text == "Python")
        assert python_verdict.status == MatchStatus.MATCHED
        assert python_verdict.method == MatchMethod.EXACT

        # 4. Unresolved LLM requirements (Kafka, Docker) cleanly marked EVALUATION_FAILED
        failed = [v for v in verdicts if v.status == MatchStatus.EVALUATION_FAILED]
        assert len(failed) == 2
        failed_skills = {v.requirement_text for v in failed}
        assert failed_skills == {"Kafka", "Docker"}


# ==============================================================================
# TEST 16 — HTTP 500 TRANSIENT SERVER ERROR DOES ROTATE KEYS
# ==============================================================================
@pytest.mark.asyncio
async def test_16_http_500_rotates_keys_until_exhaustion():
    settings = make_test_settings()
    evaluator = SmartMatchEvaluator(settings)
    service = HybridMatchingService(settings=settings, evaluator=evaluator)

    job = SimpleNamespace(
        title="Engineer",
        required_skills=["Kubernetes"],
        preferred_skills=[],
        skills=["Kubernetes"],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        certifications=[],
    )

    resume_data = SimpleNamespace(
        name="Candidate 500",
        skills=[],
        experience=[{"description": "Container orchestration with Kubernetes."}],
    )
    extracted = SimpleNamespace(
        skills=[],
        experience=[{"description": "Container orchestration with Kubernetes."}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    post_call_count = 0
    mock_resp_500 = MagicMock(spec=httpx.Response)
    mock_resp_500.status_code = 500
    mock_resp_500.json.return_value = {"error": {"message": "Internal server error", "type": "server_error"}}
    err_500 = httpx.HTTPStatusError("Server error '500 Internal Server Error'", request=MagicMock(), response=mock_resp_500)

    async def mock_post(url, headers=None, json=None, timeout=None):
        nonlocal post_call_count
        post_call_count += 1
        raise err_500

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        _, verdicts = await service.match(job, resume_data, extracted)

        # 1. Rotates through all 3 keys (3 physical attempts)
        assert post_call_count == 3

        # 2. Results in clean EVALUATION_FAILED for the requirement
        assert len(verdicts) == 1
        assert verdicts[0].status == MatchStatus.EVALUATION_FAILED


