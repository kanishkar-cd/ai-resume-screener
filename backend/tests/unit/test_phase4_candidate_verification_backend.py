"""Unit tests for Phase 4: Batch Candidate Verification Backend.

Covers:
1. Job opening resolution (by project UUID, Zoho Job Opening ID, error when not found).
2. Grouping duplicate attachments into single candidate verification tasks.
3. Independent candidate processing (individual failure resilience).
4. Full integration of Phase 1 (normalization), Phase 2 (identity matching), and Phase 3 (repeat application).
5. Progress reporting and aggregate counters (total, processed, verified, review_required, failed).
6. Safe retries (skipping already verified candidates unless force_reverify=True).
7. Status retrieval logic for frontend consumption.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4
import pytest

from app.schemas.candidate_identity import (
    CandidateIdentityRecord,
)
from app.schemas.candidate_verification import (
    BatchVerificationStatus,
    CandidateVerificationStatus,
)
from app.schemas.repeat_application import RepeatApplicationStatus
from app.services.candidate_identity_service import CandidateIdentityService
from app.services.candidate_verification_service import CandidateVerificationService
from app.services.repeat_application_service import RepeatApplicationService


# ==============================================================================
# Helper Fixtures
# ==============================================================================

@pytest.fixture
def identity_service() -> CandidateIdentityService:
    return CandidateIdentityService(session=None)


@pytest.fixture
def repeat_service(identity_service: CandidateIdentityService) -> RepeatApplicationService:
    return RepeatApplicationService(session=None, identity_service=identity_service)


@pytest.fixture
def verification_service(
    identity_service: CandidateIdentityService,
    repeat_service: RepeatApplicationService,
) -> CandidateVerificationService:
    return CandidateVerificationService(
        session=None,
        identity_service=identity_service,
        repeat_service=repeat_service,
    )


# ==============================================================================
# 1. Job Opening Resolution Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_job_opening_not_found(verification_service: CandidateVerificationService) -> None:
    # No session and no in-memory records/project
    summary = await verification_service.verify_job_opening_candidates("nonexistent-job-123")
    assert summary.status == BatchVerificationStatus.FAILED
    assert "not found" in (summary.error_message or "").lower()


@pytest.mark.asyncio
async def test_batch_verification_empty_candidates(verification_service: CandidateVerificationService) -> None:
    in_mem_proj = {
        "id": str(uuid4()),
        "zoho_job_opening_id": "ZO-EMPTY-100",
        "title": "Backend Engineer",
    }
    summary = await verification_service.verify_job_opening_candidates(
        "ZO-EMPTY-100",
        in_memory_project=in_mem_proj,
        in_memory_records=[],
    )
    assert summary.status == BatchVerificationStatus.COMPLETED
    assert summary.total_candidates == 0
    assert summary.processed_candidates == 0
    assert summary.progress_percentage == 100.0


# ==============================================================================
# 2. Grouping Duplicate Attachments (Rule 4 Workflow) Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_multiple_attachments_grouped_into_single_candidate_task(
    verification_service: CandidateVerificationService,
) -> None:
    doc1 = str(uuid4())
    doc2 = str(uuid4())
    doc3 = str(uuid4())

    # 3 resumes / attachments belonging to the SAME candidate under this job opening
    in_mem_records = [
        {
            "document_id": doc1,
            "candidate_name": "Sarah Connor",
            "email": "sarah@resistance.org",
            "phone": "+1 650 234 5678",
            "zoho_candidate_id": "ZC-SARAH-1",
            "zoho_attachment_id": "ATT-001",
        },
        {
            "document_id": doc2,
            "candidate_name": "Sarah Connor",
            "email": "sarah@resistance.org",
            "phone": "+1 650 234 5678",
            "zoho_candidate_id": "ZC-SARAH-1",
            "zoho_attachment_id": "ATT-002",
        },
        {
            "document_id": doc3,
            "candidate_name": "Sarah Connor",
            "email": "sarah@resistance.org",
            "phone": "+1 650 234 5678",
            "zoho_candidate_id": "ZC-SARAH-1",
            "zoho_attachment_id": "ATT-003",
        },
    ]

    summary = await verification_service.verify_job_opening_candidates(
        "ZO-TECH-1",
        in_memory_project={"id": str(uuid4()), "zoho_job_opening_id": "ZO-TECH-1"},
        in_memory_records=in_mem_records,
        in_memory_ats_records=[],
    )

    # Must be grouped into exactly 1 candidate verification task!
    assert summary.total_candidates == 1
    assert summary.processed_candidates == 1
    assert summary.verified_candidates == 1
    assert summary.status == BatchVerificationStatus.COMPLETED

    res = summary.results[0]
    assert set(res.document_ids) == {doc1, doc2, doc3}
    assert res.verification_status == CandidateVerificationStatus.VERIFIED
    assert res.repeat_application_status == RepeatApplicationStatus.FIRST_APPLICATION


# ==============================================================================
# 3. Independent Processing & Resilience Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_individual_candidate_failure_does_not_abort_batch(
    verification_service: CandidateVerificationService,
) -> None:
    doc1 = str(uuid4())
    doc2 = str(uuid4())

    in_mem_records = [
        {
            "document_id": doc1,
            "candidate_name": "Normal Candidate",
            "email": "normal@example.com",
            "phone": "+1 650 234 5678",
        },
        {
            "document_id": doc2,
            "candidate_name": "Faulty Candidate",
            "email": "faulty@example.com",
            "phone": "+1 650 234 5679",
        },
    ]

    # Mock _verify_single_candidate to raise an exception for the second candidate
    orig_verify = verification_service._verify_single_candidate

    async def mock_verify(group, **kwargs):
        if group["email"] == "faulty@example.com":
            raise RuntimeError("Corrupted resume payload")
        return await orig_verify(group=group, **kwargs)

    with patch.object(verification_service, "_verify_single_candidate", side_effect=mock_verify):
        summary = await verification_service.verify_job_opening_candidates(
            "ZO-MIXED-1",
            in_memory_project={"id": str(uuid4()), "zoho_job_opening_id": "ZO-MIXED-1"},
            in_memory_records=in_mem_records,
            in_memory_ats_records=[],
        )

    # Batch should gracefully complete with PARTIAL_SUCCESS, 1 verified, 1 failed
    assert summary.status == BatchVerificationStatus.PARTIAL_SUCCESS
    assert summary.total_candidates == 2
    assert summary.verified_candidates == 1
    assert summary.failed_candidates == 1
    assert summary.progress_percentage == 100.0

    faulty_res = next(r for r in summary.results if r.email == "faulty@example.com")
    assert faulty_res.verification_status == CandidateVerificationStatus.FAILED
    assert "Corrupted resume payload" in (faulty_res.error_message or "")


# ==============================================================================
# 4. Phase 1, 2, 3 Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_batch_verification_with_existing_and_repeat_candidates(
    verification_service: CandidateVerificationService,
) -> None:
    proj_id = str(uuid4())
    cand1_doc = str(uuid4())
    cand2_doc = str(uuid4())

    # Candidate 1: clean new applicant
    # Candidate 2: repeat applicant from a previous job opening (JOB-PAST-1)
    in_mem_records = [
        {
            "document_id": cand1_doc,
            "candidate_name": "Bruce Wayne",
            "email": "bruce@wayne.com",
            "phone": "+1 650 234 5678",
        },
        {
            "document_id": cand2_doc,
            "candidate_name": "Clark Kent",
            "email": "clark@dailyplanet.com",
            "phone": "+1 650 234 5679",
        },
    ]

    # Pre-existing candidate in ATS for Clark Kent in another job opening
    ats_history = [
        CandidateIdentityRecord(
            document_id=str(uuid4()),
            candidate_name="Clark Kent",
            email="clark@dailyplanet.com",
            phone="+1 650 234 5679",
            job_opening_id="JOB-PAST-1",
            job_title="Reporter",
        )
    ]

    summary = await verification_service.verify_job_opening_candidates(
        "JOB-CURRENT-2",
        in_memory_project={"id": proj_id, "zoho_job_opening_id": "JOB-CURRENT-2"},
        in_memory_records=in_mem_records,
        in_memory_ats_records=ats_history,
    )

    assert summary.status == BatchVerificationStatus.COMPLETED
    assert summary.total_candidates == 2
    assert summary.verified_candidates == 2
    assert summary.review_required_candidates == 0

    clark_res = next(r for r in summary.results if r.email == "clark@dailyplanet.com")
    assert clark_res.verification_status == CandidateVerificationStatus.VERIFIED
    assert clark_res.is_repeat_applicant is True
    assert clark_res.repeat_application_status == RepeatApplicationStatus.REPEAT_APPLICATION_DIFFERENT_JOB


@pytest.mark.asyncio
async def test_batch_verification_flags_review_required(
    verification_service: CandidateVerificationService,
) -> None:
    doc1 = str(uuid4())
    in_mem_records = [
        {
            "document_id": doc1,
            "candidate_name": "Tony Stark",
            "email": "shared.email@avengers.org",
        }
    ]

    # Existing candidate with the same email but a conflicting name
    ats_history = [
        CandidateIdentityRecord(
            document_id=str(uuid4()),
            candidate_name="Steve Rogers",
            email="shared.email@avengers.org",
            job_opening_id="JOB-DEFENSE",
        )
    ]

    summary = await verification_service.verify_job_opening_candidates(
        "JOB-AVENGERS",
        in_memory_project={"id": str(uuid4()), "zoho_job_opening_id": "JOB-AVENGERS"},
        in_memory_records=in_mem_records,
        in_memory_ats_records=ats_history,
    )

    assert summary.status == BatchVerificationStatus.PARTIAL_SUCCESS
    assert summary.total_candidates == 1
    assert summary.review_required_candidates == 1
    assert summary.results[0].verification_status == CandidateVerificationStatus.REVIEW_REQUIRED
    assert len(summary.results[0].conflicts) > 0


# ==============================================================================
# 5. Safe Retries & Status Retrieval Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_safe_retry_skips_already_verified_candidates(
    verification_service: CandidateVerificationService,
) -> None:
    doc1 = str(uuid4())
    doc2 = str(uuid4())

    in_mem_records = [
        {
            "document_id": doc1,
            "candidate_name": "Already Verified Person",
            "email": "verified@example.com",
            "phone": "+16502345678",
            "verification": {
                "candidate_identifier": "email_verified@example.com",
                "document_ids": [doc1],
                "candidate_name": "Already Verified Person",
                "email": "verified@example.com",
                "phone": "+16502345678",
                "verification_status": CandidateVerificationStatus.VERIFIED.value,
                "confidence": 1.0,
            },
        },
        {
            "document_id": doc2,
            "candidate_name": "Unverified Person",
            "email": "unverified@example.com",
            "phone": "+16502345679",
            "verification": None,
        },
    ]

    # Run safe retry (force_reverify=False)
    summary = await verification_service.retry_failed_candidates(
        "JOB-RETRY-1",
        in_memory_project={"id": str(uuid4()), "zoho_job_opening_id": "JOB-RETRY-1"},
        in_memory_records=in_mem_records,
        in_memory_ats_records=[],
    )

    assert summary.status == BatchVerificationStatus.COMPLETED
    assert summary.total_candidates == 2
    assert summary.verified_candidates == 2

    # The already-verified candidate was preserved
    preserved = next(r for r in summary.results if r.email == "verified@example.com")
    assert preserved.verification_status == CandidateVerificationStatus.VERIFIED


@pytest.mark.asyncio
async def test_get_verification_status(verification_service: CandidateVerificationService) -> None:
    # 1. Not started
    status_not_started = await verification_service.get_verification_status(
        "JOB-NOT-STARTED",
        in_memory_project={"id": str(uuid4()), "zoho_job_opening_id": "JOB-NOT-STARTED"},
    )
    assert status_not_started.status == BatchVerificationStatus.NOT_STARTED

    # 2. Existing persisted summary
    in_mem_proj = {
        "id": str(uuid4()),
        "zoho_job_opening_id": "JOB-DONE",
        "candidate_verification": {
            "batch_id": "BATCH-123",
            "job_opening_id": "JOB-DONE",
            "status": BatchVerificationStatus.COMPLETED.value,
            "total_candidates": 5,
            "processed_candidates": 5,
            "verified_candidates": 5,
            "review_required_candidates": 0,
            "failed_candidates": 0,
            "progress_percentage": 100.0,
            "results": [],
        },
    }
    status_done = await verification_service.get_verification_status(
        "JOB-DONE",
        in_memory_project=in_mem_proj,
    )
    assert status_done.status == BatchVerificationStatus.COMPLETED
    assert status_done.batch_id == "BATCH-123"
    assert status_done.total_candidates == 5


# ==============================================================================
# 6. HTTP API Endpoint Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_verify_project_candidates_endpoint() -> None:
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.api.v1.endpoints.candidate_verification import get_candidate_verification_service
    from app.schemas.candidate_verification import BatchVerificationSummary, BatchVerificationStatus

    fake_summary = BatchVerificationSummary(
        batch_id="TEST-BATCH-1",
        project_id=str(uuid4()),
        status=BatchVerificationStatus.COMPLETED,
        total_candidates=3,
        processed_candidates=3,
        verified_candidates=3,
        progress_percentage=100.0,
    )

    mock_service = AsyncMock()
    mock_service.verify_job_opening_candidates.return_value = fake_summary
    mock_service.get_verification_status.return_value = fake_summary
    mock_service.retry_failed_candidates.return_value = fake_summary

    app.dependency_overrides[get_candidate_verification_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            proj_id = str(uuid4())

            # 1. POST /projects/{project_id}/verify-candidates
            res = await client.post(f"/api/v1/projects/{proj_id}/verify-candidates", json={"force_reverify": True})
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["batch_id"] == "TEST-BATCH-1"
            assert data["status"] == "COMPLETED"

            # 2. GET /projects/{project_id}/verification-status
            res = await client.get(f"/api/v1/projects/{proj_id}/verification-status")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["batch_id"] == "TEST-BATCH-1"

            # 3. POST /projects/{project_id}/verify-candidates/retry
            res = await client.post(f"/api/v1/projects/{proj_id}/verify-candidates/retry")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["batch_id"] == "TEST-BATCH-1"

            # 4. POST /zoho/job-openings/{job_id}/verify-candidates
            res = await client.post("/api/v1/zoho/job-openings/5001/verify-candidates")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["batch_id"] == "TEST-BATCH-1"

            # 5. GET /zoho/job-openings/{job_id}/verification-status
            res = await client.get("/api/v1/zoho/job-openings/5001/verification-status")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["batch_id"] == "TEST-BATCH-1"

    finally:
        app.dependency_overrides.pop(get_candidate_verification_service, None)

