"""Unit tests for Phase 2: Candidate Verification Manual Review Endpoint & Persistence.

Covers:
1. Successful approval persistence (VERIFIED status, review decision, note, timestamp, reviewer_id).
2. Successful rejection persistence (REJECTED status, review decision, note, timestamp, reviewer_id).
3. Preservation of existing conflicts and reasons in Document metadata.
4. Document-level isolation (reviewing doc1 leaves doc2 in candidate group untouched).
5. Validation error: Missing document (HTTP 404).
6. Validation error: Missing project (HTTP 404).
7. Validation error: Project / Document mismatch (HTTP 400).
8. Validation error: Document does not require review (already VERIFIED or unverified) (HTTP 400).
9. Validation error: Invalid review decision schema (HTTP 422).
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4
import httpx
import pytest
from pydantic import ValidationError

from app.schemas.candidate_verification import (
    CandidateManualReviewRequest,
    CandidateVerificationStatus,
    ManualReviewDecision,
)
from app.services.candidate_identity_service import CandidateIdentityService
from app.services.candidate_verification_service import (
    CandidateVerificationService,
    ReviewNotRequiredException,
)
from app.services.document_service import (
    DocumentBelongsToAnotherProjectException,
    DocumentNotFoundException,
)
from app.services.project_service import ProjectNotFoundException
from app.services.repeat_application_service import RepeatApplicationService


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
# 1. Approval Persistence & Conflict Preservation Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_manual_review_approve_persists_decision_and_preserves_evidence(
    verification_service: CandidateVerificationService,
) -> None:
    proj_id = str(uuid4())
    doc_id = str(uuid4())

    in_mem_project = {
        "id": proj_id,
        "title": "Senior SRE",
        "candidate_verification": {
            "results": [
                {
                    "candidate_identifier": "zoho_1001",
                    "document_ids": [doc_id],
                    "candidate_name": "Alex Morgan",
                    "verification_status": "REVIEW_REQUIRED",
                }
            ],
            "verified_candidates": 0,
            "review_required_candidates": 1,
            "failed_candidates": 0,
        },
    }

    initial_conflicts = [
        {
            "type": "NAME_CONFLICT_ON_ZOHO_ID",
            "incoming_name": "Alex Morgan",
            "existing_name": "Alexander Morgan",
        }
    ]
    initial_reasons = ["Zoho ID matched existing record, but name differs slightly."]

    in_mem_docs = [
        {
            "id": doc_id,
            "project_id": proj_id,
            "document_type": "RESUME",
            "metadata_json": {
                "verification": {
                    "candidate_identifier": "zoho_1001",
                    "document_ids": [doc_id],
                    "candidate_name": "Alex Morgan",
                    "verification_status": "REVIEW_REQUIRED",
                    "identity_status": "REVIEW_REQUIRED",
                    "conflicts": initial_conflicts,
                    "reasons": initial_reasons,
                }
            },
        }
    ]

    payload = CandidateManualReviewRequest(
        decision=ManualReviewDecision.APPROVE,
        review_note="Confirmed identity by government ID match.",
    )

    result = await verification_service.review_candidate_document(
        project_id=proj_id,
        document_id=doc_id,
        payload=payload,
        reviewer_id="recruiter_jane@example.com",
        in_memory_project=in_mem_project,
        in_memory_documents=in_mem_docs,
    )

    # 1. Returned schema validation
    assert result.decision == ManualReviewDecision.APPROVE
    assert result.verification_status == CandidateVerificationStatus.VERIFIED
    assert result.review_note == "Confirmed identity by government ID match."
    assert result.reviewed_by == "recruiter_jane@example.com"
    assert result.reviewed_at is not None

    # 2. Document persistence verification
    saved_meta = in_mem_docs[0]["metadata_json"]["verification"]
    assert saved_meta["verification_status"] == "VERIFIED"
    assert saved_meta["review_decision"] == "APPROVE"
    assert saved_meta["review_note"] == "Confirmed identity by government ID match."
    assert saved_meta["reviewed_by"] == "recruiter_jane@example.com"
    assert saved_meta["reviewed_at"] is not None

    # 3. Evidence preservation: conflicts and original reasons MUST remain intact
    assert saved_meta["conflicts"] == initial_conflicts
    assert any("Zoho ID matched" in r for r in saved_meta["reasons"])
    assert any("Manual identity review: APPROVE" in r for r in saved_meta["reasons"])


# ==============================================================================
# 2. Rejection Persistence Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_manual_review_reject_persists_rejection(
    verification_service: CandidateVerificationService,
) -> None:
    proj_id = str(uuid4())
    doc_id = str(uuid4())

    in_mem_project = {"id": proj_id, "title": "DevOps Engineer"}
    in_mem_docs = [
        {
            "id": doc_id,
            "project_id": proj_id,
            "document_type": "RESUME",
            "metadata_json": {
                "verification": {
                    "candidate_identifier": "email_fake@example.com",
                    "document_ids": [doc_id],
                    "verification_status": "REVIEW_REQUIRED",
                    "conflicts": [{"type": "NAME_CONFLICT_ON_EMAIL"}],
                    "reasons": ["Multiple applicants applied under same email address."],
                }
            },
        }
    ]

    payload = CandidateManualReviewRequest(
        decision=ManualReviewDecision.REJECT,
        review_note="Candidate admitted using colleague's resume format with altered contact info.",
    )

    result = await verification_service.review_candidate_document(
        project_id=proj_id,
        document_id=doc_id,
        payload=payload,
        reviewer_id="lead_auditor@clouddestinations.com",
        in_memory_project=in_mem_project,
        in_memory_documents=in_mem_docs,
    )

    assert result.decision == ManualReviewDecision.REJECT
    assert result.verification_status == CandidateVerificationStatus.REJECTED

    saved_meta = in_mem_docs[0]["metadata_json"]["verification"]
    assert saved_meta["verification_status"] == "REJECTED"
    assert saved_meta["review_decision"] == "REJECT"
    assert saved_meta["reviewed_by"] == "lead_auditor@clouddestinations.com"
    assert len(saved_meta["conflicts"]) == 1


# ==============================================================================
# 3. Document-Level Isolation Tests (Per-Resume Decision Scope)
# ==============================================================================


@pytest.mark.asyncio
async def test_manual_review_document_level_isolation(
    verification_service: CandidateVerificationService,
) -> None:
    """Verifying doc1 must leave doc2 for the same candidate completely untouched."""
    proj_id = str(uuid4())
    doc1_id = str(uuid4())
    doc2_id = str(uuid4())

    in_mem_project = {
        "id": proj_id,
        "title": "Cloud Architect",
        "candidate_verification": {
            "results": [
                {
                    "candidate_identifier": "zoho_cand_777",
                    "document_ids": [doc1_id, doc2_id],
                    "candidate_name": "Taylor Swift",
                    "verification_status": "REVIEW_REQUIRED",
                }
            ],
            "verified_candidates": 0,
            "review_required_candidates": 1,
            "failed_candidates": 0,
        },
    }

    in_mem_docs = [
        {
            "id": doc1_id,
            "project_id": proj_id,
            "document_type": "RESUME",
            "metadata_json": {
                "verification": {
                    "candidate_identifier": "zoho_cand_777",
                    "document_ids": [doc1_id, doc2_id],
                    "candidate_name": "Taylor Swift",
                    "verification_status": "REVIEW_REQUIRED",
                    "conflicts": [{"type": "NAME_CONFLICT"}],
                    "reasons": ["Resume 1 conflict."],
                }
            },
        },
        {
            "id": doc2_id,
            "project_id": proj_id,
            "document_type": "RESUME",
            "metadata_json": {
                "verification": {
                    "candidate_identifier": "zoho_cand_777",
                    "document_ids": [doc1_id, doc2_id],
                    "candidate_name": "Taylor Swift",
                    "verification_status": "REVIEW_REQUIRED",
                    "conflicts": [{"type": "NAME_CONFLICT"}],
                    "reasons": ["Resume 2 conflict."],
                }
            },
        },
    ]

    # Review ONLY doc1
    payload = CandidateManualReviewRequest(
        decision=ManualReviewDecision.APPROVE,
        review_note="Approved primary resume version.",
    )

    await verification_service.review_candidate_document(
        project_id=proj_id,
        document_id=doc1_id,
        payload=payload,
        in_memory_project=in_mem_project,
        in_memory_documents=in_mem_docs,
    )

    # doc1 is now VERIFIED
    assert in_mem_docs[0]["metadata_json"]["verification"]["verification_status"] == "VERIFIED"
    assert in_mem_docs[0]["metadata_json"]["verification"]["review_decision"] == "APPROVE"

    # doc2 MUST REMAIN untouched in REVIEW_REQUIRED
    assert in_mem_docs[1]["metadata_json"]["verification"]["verification_status"] == "REVIEW_REQUIRED"
    assert "review_decision" not in in_mem_docs[1]["metadata_json"]["verification"]


# ==============================================================================
# 4. Validation & Error Handling Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_manual_review_project_not_found(
    verification_service: CandidateVerificationService,
) -> None:
    nonexistent_proj = str(uuid4())
    doc_id = str(uuid4())

    payload = CandidateManualReviewRequest(decision=ManualReviewDecision.APPROVE)

    with pytest.raises(ProjectNotFoundException):
        await verification_service.review_candidate_document(
            project_id=nonexistent_proj,
            document_id=doc_id,
            payload=payload,
            in_memory_project={"id": str(uuid4())},
            in_memory_documents=[],
        )


@pytest.mark.asyncio
async def test_manual_review_document_not_found(
    verification_service: CandidateVerificationService,
) -> None:
    proj_id = str(uuid4())
    nonexistent_doc = str(uuid4())

    payload = CandidateManualReviewRequest(decision=ManualReviewDecision.APPROVE)

    with pytest.raises(DocumentNotFoundException):
        await verification_service.review_candidate_document(
            project_id=proj_id,
            document_id=nonexistent_doc,
            payload=payload,
            in_memory_project={"id": proj_id},
            in_memory_documents=[],
        )


@pytest.mark.asyncio
async def test_manual_review_document_project_mismatch(
    verification_service: CandidateVerificationService,
) -> None:
    proj_a = str(uuid4())
    proj_b = str(uuid4())
    doc_id = str(uuid4())

    payload = CandidateManualReviewRequest(decision=ManualReviewDecision.APPROVE)

    # Document belongs to proj_b, but request targets proj_a
    in_mem_docs = [
        {
            "id": doc_id,
            "project_id": proj_b,
            "document_type": "RESUME",
            "metadata_json": {"verification": {"verification_status": "REVIEW_REQUIRED"}},
        }
    ]

    with pytest.raises(DocumentBelongsToAnotherProjectException):
        await verification_service.review_candidate_document(
            project_id=proj_a,
            document_id=doc_id,
            payload=payload,
            in_memory_project={"id": proj_a},
            in_memory_documents=in_mem_docs,
        )


@pytest.mark.asyncio
async def test_manual_review_not_required_when_already_verified(
    verification_service: CandidateVerificationService,
) -> None:
    proj_id = str(uuid4())
    doc_id = str(uuid4())

    payload = CandidateManualReviewRequest(decision=ManualReviewDecision.APPROVE)

    in_mem_docs = [
        {
            "id": doc_id,
            "project_id": proj_id,
            "document_type": "RESUME",
            "metadata_json": {
                "verification": {
                    "verification_status": "VERIFIED",
                }
            },
        }
    ]

    with pytest.raises(ReviewNotRequiredException) as excinfo:
        await verification_service.review_candidate_document(
            project_id=proj_id,
            document_id=doc_id,
            payload=payload,
            in_memory_project={"id": proj_id},
            in_memory_documents=in_mem_docs,
        )
    assert "does not require review" in str(excinfo.value)
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_manual_review_not_required_when_unverified(
    verification_service: CandidateVerificationService,
) -> None:
    proj_id = str(uuid4())
    doc_id = str(uuid4())

    payload = CandidateManualReviewRequest(decision=ManualReviewDecision.APPROVE)

    in_mem_docs = [
        {
            "id": doc_id,
            "project_id": proj_id,
            "document_type": "RESUME",
            "metadata_json": {},  # No verification run yet
        }
    ]

    with pytest.raises(ReviewNotRequiredException) as excinfo:
        await verification_service.review_candidate_document(
            project_id=proj_id,
            document_id=doc_id,
            payload=payload,
            in_memory_project={"id": proj_id},
            in_memory_documents=in_mem_docs,
        )
    assert excinfo.value.status_code == 400


def test_invalid_decision_fails_pydantic_validation() -> None:
    with pytest.raises(ValidationError):
        CandidateManualReviewRequest.model_validate({"decision": "MAYBE"})


# ==============================================================================
# 5. FastAPI Route & HTTP Status Code Tests (via AsyncClient)
# ==============================================================================


@pytest.mark.asyncio
async def test_api_review_endpoint_success(async_client: httpx.AsyncClient) -> None:
    from app.main import app
    from app.api.v1.endpoints.candidate_verification import get_candidate_verification_service

    proj_id = uuid4()
    doc_id = uuid4()

    in_mem_project = {
        "id": str(proj_id),
        "title": "Staff Engineer",
        "candidate_verification": {
            "results": [
                {
                    "candidate_identifier": "zoho_cand_999",
                    "document_ids": [str(doc_id)],
                    "candidate_name": "Jordan Lee",
                    "verification_status": "REVIEW_REQUIRED",
                }
            ],
            "verified_candidates": 0,
            "review_required_candidates": 1,
            "failed_candidates": 0,
        },
    }

    in_mem_docs = [
        {
            "id": str(doc_id),
            "project_id": str(proj_id),
            "document_type": "RESUME",
            "metadata_json": {
                "verification": {
                    "candidate_identifier": "zoho_cand_999",
                    "document_ids": [str(doc_id)],
                    "candidate_name": "Jordan Lee",
                    "verification_status": "REVIEW_REQUIRED",
                    "conflicts": [{"type": "NAME_CONFLICT"}],
                    "reasons": ["Name conflict detected."],
                }
            },
        }
    ]

    class FakeService(CandidateVerificationService):
        def __init__(self) -> None:
            super().__init__(session=None)

        async def review_candidate_document(
            self,
            project_id: UUID | str,
            document_id: UUID | str,
            payload: CandidateManualReviewRequest,
            reviewer_id: str | None = None,
            **kwargs,
        ):
            return await super().review_candidate_document(
                project_id=project_id,
                document_id=document_id,
                payload=payload,
                reviewer_id=reviewer_id,
                in_memory_project=in_mem_project,
                in_memory_documents=in_mem_docs,
            )

    app.dependency_overrides[get_candidate_verification_service] = lambda: FakeService()

    try:
        res = await async_client.post(
            f"/api/v1/projects/{proj_id}/documents/{doc_id}/review",
            json={"decision": "APPROVE", "review_note": "Confirmed identity in person."},
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()["data"]
        assert data["decision"] == "APPROVE"
        assert data["verification_status"] == "VERIFIED"
        assert data["review_note"] == "Confirmed identity in person."
        assert in_mem_docs[0]["metadata_json"]["verification"]["verification_status"] == "VERIFIED"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_review_endpoint_invalid_payload_422(async_client: httpx.AsyncClient) -> None:
    proj_id = uuid4()
    doc_id = uuid4()

    res = await async_client.post(
        f"/api/v1/projects/{proj_id}/documents/{doc_id}/review",
        json={"decision": "NOT_AN_OPTION"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_api_review_endpoint_project_mismatch_400(async_client: httpx.AsyncClient) -> None:
    from app.main import app
    from app.api.v1.endpoints.candidate_verification import get_candidate_verification_service

    proj_id = uuid4()
    doc_id = uuid4()

    # Document belongs to a different project
    in_mem_project = {"id": str(proj_id)}
    in_mem_docs = [
        {
            "id": str(doc_id),
            "project_id": str(uuid4()),  # different project
            "document_type": "RESUME",
            "metadata_json": {"verification": {"verification_status": "REVIEW_REQUIRED"}},
        }
    ]

    class FakeService(CandidateVerificationService):
        def __init__(self) -> None:
            super().__init__(session=None)

        async def review_candidate_document(
            self,
            project_id: UUID | str,
            document_id: UUID | str,
            payload: CandidateManualReviewRequest,
            reviewer_id: str | None = None,
            **kwargs,
        ):
            return await super().review_candidate_document(
                project_id=project_id,
                document_id=document_id,
                payload=payload,
                reviewer_id=reviewer_id,
                in_memory_project=in_mem_project,
                in_memory_documents=in_mem_docs,
            )

    app.dependency_overrides[get_candidate_verification_service] = lambda: FakeService()

    try:
        res = await async_client.post(
            f"/api/v1/projects/{proj_id}/documents/{doc_id}/review",
            json={"decision": "APPROVE"},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "DOCUMENT_PROJECT_MISMATCH"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_review_endpoint_review_not_required_400(async_client: httpx.AsyncClient) -> None:
    from app.main import app
    from app.api.v1.endpoints.candidate_verification import get_candidate_verification_service

    proj_id = uuid4()
    doc_id = uuid4()

    in_mem_project = {"id": str(proj_id)}
    in_mem_docs = [
        {
            "id": str(doc_id),
            "project_id": str(proj_id),
            "document_type": "RESUME",
            "metadata_json": {"verification": {"verification_status": "VERIFIED"}},
        }
    ]

    class FakeService(CandidateVerificationService):
        def __init__(self) -> None:
            super().__init__(session=None)

        async def review_candidate_document(
            self,
            project_id: UUID | str,
            document_id: UUID | str,
            payload: CandidateManualReviewRequest,
            reviewer_id: str | None = None,
            **kwargs,
        ):
            return await super().review_candidate_document(
                project_id=project_id,
                document_id=document_id,
                payload=payload,
                reviewer_id=reviewer_id,
                in_memory_project=in_mem_project,
                in_memory_documents=in_mem_docs,
            )

    app.dependency_overrides[get_candidate_verification_service] = lambda: FakeService()

    try:
        res = await async_client.post(
            f"/api/v1/projects/{proj_id}/documents/{doc_id}/review",
            json={"decision": "APPROVE"},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "REVIEW_NOT_REQUIRED"
    finally:
        app.dependency_overrides.clear()

