import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.schemas.matching import Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind
from app.services.matching_service import GroqMatchEvaluator, HybridMatchingService


@pytest.fixture
def evaluator() -> GroqMatchEvaluator:
    GroqMatchEvaluator._cache.clear()
    eval = GroqMatchEvaluator()
    eval.settings.ENABLE_HYBRID_MATCHING = True
    eval.settings.GROQ_API_KEY = "mock-groq-key-secret"
    eval.settings.GROQ_MAX_RETRIES = 2
    return eval


@pytest.mark.asyncio
async def test_1_successful_request_no_retry(evaluator: GroqMatchEvaluator) -> None:
    """1. Successful request -> no retry."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    valid_response_data = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "verdicts": [{
                        "requirement_id": "responsibility:1",
                        "status": "MATCHED",
                        "confidence": 0.95,
                        "evidence_ids": ["project:1"],
                        "reasoning": "Built REST APIs in project:1",
                    }]
                })
            }
        }]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = valid_response_data

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        res = await evaluator.evaluate(reqs, evidence)

    assert len(res) == 1
    assert res[0].status == MatchStatus.MATCHED
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_2_first_request_429_second_succeeds(evaluator: GroqMatchEvaluator) -> None:
    """2. First request returns 429, second succeeds -> retry occurs and final result is returned."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_429 = MagicMock()
    req_429.status_code = 429
    req_429.headers = {"Retry-After": "0.01"}
    err_429 = httpx.HTTPStatusError("Rate Limit", request=MagicMock(), response=req_429)
    req_429.raise_for_status.side_effect = err_429

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.raise_for_status = MagicMock()
    mock_resp_200.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "verdicts": [{
                        "requirement_id": "responsibility:1",
                        "status": "MATCHED",
                        "confidence": 0.9,
                        "evidence_ids": ["project:1"],
                        "reasoning": "Match confirmed on second attempt",
                    }]
                })
            }
        }]
    }

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_429, mock_resp_200]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await evaluator.evaluate(reqs, evidence)

    assert len(res) == 1
    assert res[0].status == MatchStatus.MATCHED
    assert mock_client.post.call_count == 2
    mock_sleep.assert_called_once_with(0.01)


@pytest.mark.asyncio
async def test_3_repeated_429_stops_at_configured_maximum(evaluator: GroqMatchEvaluator) -> None:
    """3. Repeated 429 -> retries stop at configured maximum (GROQ_MAX_RETRIES + 1 attempts)."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_429 = MagicMock()
    req_429.status_code = 429
    req_429.headers = {}
    err_429 = httpx.HTTPStatusError("Rate Limit Exceeded", request=MagicMock(), response=req_429)
    req_429.raise_for_status.side_effect = err_429

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_429, req_429, req_429]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await evaluator.evaluate(reqs, evidence)

    assert res == []
    # Evaluator has GROQ_MAX_RETRIES = 2 -> total 3 attempts (1 initial + 2 retries)
    assert mock_client.post.call_count == 3
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_4_retry_after_header_is_respected(evaluator: GroqMatchEvaluator) -> None:
    """4. Retry-After header is present -> Retry-After is respected."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_429 = MagicMock()
    req_429.status_code = 429
    req_429.headers = {"Retry-After": "3.5"}
    err_429 = httpx.HTTPStatusError("Rate Limit", request=MagicMock(), response=req_429)
    req_429.raise_for_status.side_effect = err_429

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.raise_for_status = MagicMock()
    mock_resp_200.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"verdicts": []})}}]
    }

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_429, mock_resp_200]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await evaluator.evaluate(reqs, evidence)

    mock_sleep.assert_called_once_with(3.5)


@pytest.mark.asyncio
async def test_5_retry_after_missing_uses_bounded_exponential_backoff(evaluator: GroqMatchEvaluator) -> None:
    """5. Retry-After missing -> bounded exponential backoff is used (2.0s, 4.0s)."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_429 = MagicMock()
    req_429.status_code = 429
    req_429.headers = {}
    err_429 = httpx.HTTPStatusError("Rate Limit", request=MagicMock(), response=req_429)
    req_429.raise_for_status.side_effect = err_429

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_429, req_429, req_429]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await evaluator.evaluate(reqs, evidence)

    assert mock_sleep.call_count == 2
    # Attempt 0 backoff: 2.0 * (2^0) = 2.0s
    assert mock_sleep.call_args_list[0][0][0] == 2.0
    # Attempt 1 backoff: 2.0 * (2^1) = 4.0s
    assert mock_sleep.call_args_list[1][0][0] == 4.0


@pytest.mark.asyncio
async def test_6_non_429_client_error_stops_retries_immediately(evaluator: GroqMatchEvaluator) -> None:
    """6. Non-429 HTTP client error (401 Unauthorized) -> stops retries immediately."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_401 = MagicMock()
    req_401.status_code = 401
    err_401 = httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=req_401)
    req_401.raise_for_status.side_effect = err_401

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_401, req_401]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await evaluator.evaluate(reqs, evidence)

    assert res == []
    assert mock_client.post.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_7_final_429_failure_does_not_create_fake_matched_result(evaluator: GroqMatchEvaluator) -> None:
    """7. Final 429 failure -> no fake MATCHED result (returns [])."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_429 = MagicMock()
    req_429.status_code = 429
    err_429 = httpx.HTTPStatusError("Rate Limit", request=MagicMock(), response=req_429)
    req_429.raise_for_status.side_effect = err_429

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_429, req_429, req_429]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock):
        res = await evaluator.evaluate(reqs, evidence)

    assert res == []


@pytest.mark.asyncio
async def test_8_final_429_failure_preserves_safe_deterministic_verdicts() -> None:
    """8. Final 429 failure -> deterministic/fallback behavior remains safe."""
    job = SimpleNamespace(
        required_skills=["Python"],
        preferred_skills=[],
        responsibilities=["Perform vulnerability triage with Splunk SIEM and Snort NIDS."],
        degree_requirements=[],
        experience_requirements=[],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    resume = SimpleNamespace(
        skills=["Python"],
        projects=[{"name": "Python Script", "description": "Simple script.", "technologies": ["Python"]}],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    extracted = SimpleNamespace(
        skills=["Python"],
        projects=resume.projects,
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )

    class FailingEvaluator:
        async def evaluate(self, requirements, evidence, allowed_evidence=None):
            return []

    hybrid = HybridMatchingService(evaluator=FailingEvaluator())
    enriched, fused = await hybrid.match(job, resume, extracted, config=None)
    resp_verdict = next(v for v in fused if v.requirement_id == "responsibility:1")
    # Non-matched responsibility remains UNRESOLVED / NO_MATCH, NOT demoted or fake MATCHED
    assert resp_verdict.status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


@pytest.mark.asyncio
async def test_9_retry_does_not_mutate_request_payload(evaluator: GroqMatchEvaluator) -> None:
    """9. Retry does not mutate the original request payload across attempts."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_429 = MagicMock()
    req_429.status_code = 429
    err_429 = httpx.HTTPStatusError("Rate Limit", request=MagicMock(), response=req_429)
    req_429.raise_for_status.side_effect = err_429

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_429, req_429, req_429]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock):
        await evaluator.evaluate(reqs, evidence)

    assert mock_client.post.call_count == 3
    payload_1 = mock_client.post.call_args_list[0].kwargs["json"]
    payload_2 = mock_client.post.call_args_list[1].kwargs["json"]
    payload_3 = mock_client.post.call_args_list[2].kwargs["json"]
    assert payload_1 == payload_2 == payload_3


@pytest.mark.asyncio
async def test_10_no_infinite_retry_loop(evaluator: GroqMatchEvaluator) -> None:
    """10. No infinite retry loop -> stops cleanly after max retries."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_503 = MagicMock()
    req_503.status_code = 503
    err_503 = httpx.HTTPStatusError("Service Unavailable", request=MagicMock(), response=req_503)
    req_503.raise_for_status.side_effect = err_503

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_503] * 10

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock):
        res = await evaluator.evaluate(reqs, evidence)

    assert res == []
    # Evaluator stops at max_retries + 1 (3 calls total), does not make 10 calls
    assert mock_client.post.call_count == 3


@pytest.mark.asyncio
async def test_11_logging_contains_attempt_status_delay_information(evaluator: GroqMatchEvaluator) -> None:
    """11. Logging contains attempt/status/delay information."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_429 = MagicMock()
    req_429.status_code = 429
    req_429.headers = {"Retry-After": "1.5"}
    err_429 = httpx.HTTPStatusError("Rate Limit", request=MagicMock(), response=req_429)
    req_429.raise_for_status.side_effect = err_429

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_429, req_429, req_429]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock), patch("app.services.matching_service.logger.warning") as mock_log:
        await evaluator.evaluate(reqs, evidence)

    assert mock_log.call_count >= 1
    log_call = mock_log.call_args_list[0]
    assert log_call[0][0] == "hybrid_match_llm_attempt_failed"
    assert log_call.kwargs.get("attempt") == 1
    assert log_call.kwargs.get("status_code") == 429
    assert log_call.kwargs.get("delay_seconds") == 1.5
    assert log_call.kwargs.get("used_retry_after") is True


@pytest.mark.asyncio
async def test_12_api_credentials_not_exposed_in_logs(evaluator: GroqMatchEvaluator) -> None:
    """12. API credentials are not exposed in logs."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]

    req_429 = MagicMock()
    req_429.status_code = 429
    err_429 = httpx.HTTPStatusError("Rate Limit", request=MagicMock(), response=req_429)
    req_429.raise_for_status.side_effect = err_429

    mock_client = AsyncMock()
    mock_client.post.side_effect = [req_429, req_429, req_429]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock), patch("app.services.matching_service.logger.warning") as mock_log:
        await evaluator.evaluate(reqs, evidence)

    for call in mock_log.call_args_list:
        log_str = str(call)
        assert "mock-groq-key-secret" not in log_str
