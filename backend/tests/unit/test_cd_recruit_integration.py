from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4
import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import ValidationException
from app.services.cd_recruit_mapper import calibrate_experience, map_department_code
from app.services.cd_recruit_poller import CDRecruitStatusPoller
from app.services.cd_recruit_service import CDRecruitException, CDRecruitService
from app.services.email_service import EmailService


class DummySettings(Settings):
    CD_RECRUIT_BASE_URL: str = "http://localhost:3001"
    CD_RECRUIT_API_KEY: str = "test-secret-api-key-123"
    CD_RECRUIT_TIMEOUT_SECONDS: float = 5.0
    CD_RECRUIT_DEFAULT_DEPARTMENT_CODE: str = "SOFTWARE_ENGINEERING"
    ENABLE_ASSESSMENT_EMAILS: bool = True


# 1. Candidate push -> HTTP 201 Created & 2. X-API-Key & 3. UUID v4 Idempotency-Key
@pytest.mark.asyncio
async def test_candidate_push_success_201():
    settings = Settings(
        CD_RECRUIT_BASE_URL="http://localhost:3001",
        CD_RECRUIT_API_KEY="test-secret-api-key-123",
        CD_RECRUIT_TIMEOUT_SECONDS=5.0,
    )
    service = CDRecruitService(settings=settings)

    mock_resp = MagicMock(status_code=201)
    mock_resp.json.return_value = {
        "drive_id": "drive_abc123",
        "invites": [
            {
                "external_candidate_ref": "doc_1",
                "assessment_link": "http://localhost:3001/invite/abc",
                "expires_at": "2026-12-31T23:59:59Z",
            }
        ],
    }

    captured_headers = {}

    async def mock_post(url, **kwargs):
        nonlocal captured_headers
        captured_headers = kwargs.get("headers", {})
        return mock_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await service.send_candidates(
            requisition_ref="REQ-123",
            department_code="SOFTWARE_ENGINEERING",
            category="EXPERIENCED",
            drive_name="Test Drive",
            candidates=[{"name": "Jane Doe", "email": "jane@example.com", "level": "2-5", "external_candidate_ref": "doc_1"}],
        )
        assert result["drive_id"] == "drive_abc123"
        assert captured_headers["X-API-Key"] == "test-secret-api-key-123"
        # Validate Idempotency-Key is UUID v4 string
        idempotency_key = captured_headers["Idempotency-Key"]
        parsed_uuid = UUID(idempotency_key)
        assert str(parsed_uuid) == idempotency_key


# 4. Same Idempotency-Key across retries on HTTP 500/503
@pytest.mark.asyncio
async def test_idempotency_key_reused_on_retry():
    settings = DummySettings()
    service = CDRecruitService(settings=settings)

    mock_fail = MagicMock(status_code=500, text="Internal Server Error")
    mock_success = MagicMock(status_code=201)
    mock_success.json.return_value = {"drive_id": "drive_999", "invites": []}

    used_keys = []

    async def mock_post(url, **kwargs):
        used_keys.append(kwargs["headers"]["Idempotency-Key"])
        if len(used_keys) == 1:
            return mock_fail
        return mock_success

    with patch("httpx.AsyncClient.post", side_effect=mock_post), patch("asyncio.sleep", return_value=None):
        result = await service.send_candidates(
            requisition_ref="REQ-500-RETRY",
            department_code="SOFTWARE_ENGINEERING",
            category="EXPERIENCED",
            drive_name="Test Drive",
            candidates=[{"name": "Jane", "email": "jane@example.com", "level": "2-5", "external_candidate_ref": "doc_1"}],
            idempotency_key="batch-fixed-uuid-key-123",
        )
        assert len(used_keys) == 2
        assert used_keys[0] == "batch-fixed-uuid-key-123"
        assert used_keys[1] == "batch-fixed-uuid-key-123"


# 5. 429 + Retry-After header
@pytest.mark.asyncio
async def test_rate_limit_429_respects_retry_after():
    settings = DummySettings()
    service = CDRecruitService(settings=settings)

    mock_429 = MagicMock(status_code=429, headers={"Retry-After": "2"})
    mock_201 = MagicMock(status_code=201)
    mock_201.json.return_value = {"drive_id": "drive_429", "invites": []}

    calls = []
    sleeps = []

    async def mock_post(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return mock_429
        return mock_201

    async def mock_sleep(seconds):
        sleeps.append(seconds)

    with patch("httpx.AsyncClient.post", side_effect=mock_post), patch("asyncio.sleep", side_effect=mock_sleep):
        result = await service.send_candidates(
            requisition_ref="REQ-429",
            department_code="SOFTWARE_ENGINEERING",
            category="FRESHER",
            drive_name="Drive 429",
            candidates=[{"name": "Bob", "email": "bob@example.com", "level": "0-1", "external_candidate_ref": "doc_2"}],
        )
        assert len(calls) == 2
        assert sleeps == [2.0]


# 6 & 7. 500 / 503 Retry
@pytest.mark.asyncio
async def test_500_503_retries():
    settings = DummySettings()
    service = CDRecruitService(settings=settings)

    mock_503 = MagicMock(status_code=503, text="Service Unavailable")
    mock_201 = MagicMock(status_code=201)
    mock_201.json.return_value = {"drive_id": "drive_503", "invites": []}

    attempts = 0

    async def mock_post(url, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return mock_503
        return mock_201

    with patch("httpx.AsyncClient.post", side_effect=mock_post), patch("asyncio.sleep", return_value=None):
        result = await service.send_candidates(
            requisition_ref="REQ-503",
            department_code="QA",
            category="FRESHER",
            drive_name="QA Drive",
            candidates=[],
        )
        assert attempts == 2
        assert result["drive_id"] == "drive_503"


# 8, 9, 10, 11. Fail-fast on 400, 401, 409, 422
@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 409, 422])
async def test_non_retryable_status_codes_fail_fast(status_code):
    settings = DummySettings()
    service = CDRecruitService(settings=settings)

    mock_resp = MagicMock(status_code=status_code, text=f"Error {status_code}")
    attempts = 0

    async def mock_post(url, **kwargs):
        nonlocal attempts
        attempts += 1
        return mock_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        with pytest.raises(CDRecruitException) as exc_info:
            await service.send_candidates(
                requisition_ref="REQ-FAIL",
                department_code="SOFTWARE_ENGINEERING",
                category="FRESHER",
                drive_name="Fail Drive",
                candidates=[],
            )
        assert attempts == 1
        assert f"non-retryable status {status_code}" in str(exc_info.value)


# 12. Department Mapping (8 Strict Codes & Rejection of Invalid Code)
def test_department_mapping_strict_codes():
    assert map_department_code("SOFTWARE_ENGINEERING") == "SOFTWARE_ENGINEERING"
    assert map_department_code("Data Engineering") == "DATA_ENGINEERING"
    assert map_department_code("PMO") == "PMO"
    assert map_department_code("Testing") == "QA"
    assert map_department_code("System Operations") == "SYSOPS"
    assert map_department_code("IT Operations") == "ITOPS"
    assert map_department_code("Security") == "SECOPS"
    assert map_department_code("DevOps") == "SRE"

    with pytest.raises(ValidationException):
        map_department_code("INVALID_DEPT_NAME", default_code="")


# 13. Experience / Category / Level Mapping Calibration & Boundary Tests
@pytest.mark.parametrize(
    "months,expected_category,expected_tier",
    [
        (12, "FRESHER", "0-1"),       # 1 year -> 0-1 / FRESHER
        (23, "FRESHER", "0-1"),       # 1.9 years -> 0-1 / FRESHER
        (24, "EXPERIENCED", "2-5"),   # 2 years -> 2-5 / EXPERIENCED
        (48, "EXPERIENCED", "2-5"),   # 4+ years -> 2-5 / EXPERIENCED
        (71, "EXPERIENCED", "2-5"),   # 5.9 years -> 2-5 / EXPERIENCED
        (72, "EXPERIENCED", "6-10"),  # 6 years -> 6-10 / EXPERIENCED
        (96, "EXPERIENCED", "6-10"),  # 8 years -> 6-10 / EXPERIENCED
        (131, "EXPERIENCED", "6-10"), # 10.9 years -> 6-10 / EXPERIENCED
        (132, "EXPERIENCED", "11-15"),# 11 years -> 11-15 / EXPERIENCED
        (144, "EXPERIENCED", "11-15"),# 12+ years -> 11-15 / EXPERIENCED
    ]
)
def test_experience_calibration_rules(months, expected_category, expected_tier):
    from app.services.cd_recruit_mapper import get_experience_tier
    cat, tier = calibrate_experience(months)
    assert cat == expected_category
    assert tier == expected_tier
    assert get_experience_tier(months) == expected_tier


def test_mixed_experience_batch_retains_individual_tiers():
    from app.services.cd_recruit_mapper import calibrate_experience
    candidates_exp = [
        {"name": "Candidate A (4 yrs)", "months": 48},
        {"name": "Candidate B (8 yrs)", "months": 96},
        {"name": "Candidate C (12 yrs)", "months": 144},
    ]

    mapped_tiers = [calibrate_experience(c["months"])[1] for c in candidates_exp]
    assert mapped_tiers == ["2-5", "6-10", "11-15"]


# 21, 23, 24, 25. Status Polling, not_graded Handling, Graded Result & Decision Persistence
@pytest.mark.asyncio
async def test_status_polling_and_not_graded_handling():
    settings = DummySettings()
    service = CDRecruitService(settings=settings)

    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "requisition_ref": "REQ-POLLED-123",
        "drive_id": "drive_polled",
        "session_status": "submitted",
        "score_status": "not_graded",
        "composite_score_band": None,
        "decision": None,
    }

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        status_data = await service.get_requisition_status("REQ-POLLED-123")
        assert status_data["session_status"] == "submitted"
        assert status_data["score_status"] == "not_graded"
        assert status_data["composite_score_band"] is None
        assert status_data["decision"] is None


@pytest.mark.asyncio
async def test_poller_updates_graded_decision():
    poller = CDRecruitStatusPoller()

    mock_status_data = {
        "session_status": "submitted",
        "score_status": "graded",
        "composite_score_band": "BAND_A",
        "decision": "advance",
    }

    with patch.object(poller.cd_recruit, "get_requisition_status", return_value=mock_status_data):
        result = await poller.poll_requisition("REQ-POLLED-456")
        assert result["session_status"] == "submitted"
        assert result["score_status"] == "graded"
        assert result["composite_score_band"] == "BAND_A"
        assert result["decision"] == "advance"
