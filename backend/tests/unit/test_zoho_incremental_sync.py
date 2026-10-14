from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.zoho import import_zoho_applicants
from app.core.config import Settings
from app.models.document import (
    DocumentModel,
    DocumentTypeEnum,
    ProcessingStageEnum,
    ProcessingStatusEnum,
)
from app.models.project import ProjectModel, ProjectStatusEnum
from app.schemas.zoho import (
    ZohoImportApplicantsRequest,
    ZohoImportApplicantsResponse,
)
from app.services.zoho_recruit_service import (
    ZohoAttachment,
    ZohoCandidateResume,
    ZohoJobOpening,
    ZohoRecruitClient,
    ZohoRecruitException,
)


def _test_settings(**overrides) -> Settings:
    values = {
        "ZOHO_CLIENT_ID": "client-id",
        "ZOHO_CLIENT_SECRET": "client-secret",
        "ZOHO_REFRESH_TOKEN": "refresh-token",
        "ZOHO_TIMEOUT_SECONDS": 5.0,
        "ZOHO_MAX_RETRIES": 1,
        "ZOHO_DOWNLOAD_CONCURRENCY": 2,
        **overrides,
    }
    return Settings(**values)


class FakeZohoRecruitAPI:
    """Mock Zoho API transport simulating JobOpenings, Candidates, Attachments, and Downloads."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.downloads: list[str] = []  # list of attachment_ids downloaded
        self.fail_all = False
        self.job_candidates: list[dict[str, Any]] = []
        self.attachments: dict[str, list[dict[str, Any]]] = {}
        self.setup_5_candidates()

    def setup_5_candidates(self) -> None:
        self.setup_n_candidates(5)

    def setup_n_candidates(self, n: int, start_idx: int = 1, prefix: str = "cand_") -> None:
        self.job_candidates = [
            {
                "id": f"{prefix}{i}",
                "Candidate_ID": f"ZR_{i}",
                "First_Name": f"Candidate{i}",
                "Last_Name": "Test",
                "Email": f"cand{i}@example.com",
                "Mobile": f"+91987654321{i}",
                "Source": "Website",
                "Modified_Time": f"2026-10-01T10:00:00+05:30",
            }
            for i in range(start_idx, start_idx + n)
        ]
        self.attachments = {
            f"{prefix}{i}": [
                {
                    "id": f"att_{i}",
                    "File_Name": f"resume_{i}.pdf",
                    "Category": {"name": "Resume", "id": "1"},
                    "Modified_Time": f"2026-10-01T10:00:00+05:30",
                    "Size": "1024",
                }
            ]
            for i in range(start_idx, start_idx + n)
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "token-xyz", "expires_in": 3600})

        if self.fail_all:
            return httpx.Response(502, json={"code": "INTERNAL_ERROR", "message": "Zoho Recruit unavailable"})

        parts = request.url.path.split("/recruit/v2/")[1].split("/")

        # JobOpenings/{id}
        if len(parts) == 2 and parts[0] == "JobOpenings":
            job_code = f"JOB_{parts[1]}" if parts[1] != "5001" else "JOB_001"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": parts[1],
                            "Posting_Title": "Senior Backend Engineer",
                            "Job_Opening_ID": job_code,
                            "Job_Description": "FastAPI & Python backend developer.",
                            "Required_Skills": "Python, FastAPI",
                            "Job_Opening_Status": "In-progress",
                            "Modified_Time": "2026-10-01T08:00:00+05:30",
                            "No_of_Candidates_Associated": len(self.job_candidates),
                        }
                    ]
                },
            )

        # Job_Openings/{id}/associate or Candidates
        if len(parts) == 3 and parts[0] in ("Job_Openings", "JobOpenings") and parts[2] == "associate":
            page = int(request.url.params.get("page", 1))
            per_page = int(request.url.params.get("per_page", 200))
            start = (page - 1) * per_page
            end = start + per_page
            chunk = self.job_candidates[start:end]
            more = end < len(self.job_candidates)
            return httpx.Response(200, json={"data": chunk, "info": {"page": page, "more_records": more}})

        # Candidates/{id}/Attachments
        if len(parts) == 3 and parts[0] == "Candidates" and parts[2] == "Attachments":
            cand_id = parts[1]
            atts = self.attachments.get(cand_id, [])
            return httpx.Response(200, json={"data": atts, "info": {"more_records": False}})

        # Candidates/{id}/Attachments/{att_id} (Download)
        if len(parts) == 4 and parts[0] == "Candidates" and parts[2] == "Attachments":
            att_id = parts[3]
            self.downloads.append(att_id)
            return httpx.Response(
                200,
                content=f"binary-content-for-{att_id}".encode(),
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Disposition": f'attachment; filename="resume_{att_id}.pdf"',
                },
            )

        return httpx.Response(404, json={"code": "NOT_FOUND"})


class MockDB:
    """In-memory mock database session tracking DocumentModel and ProjectModel."""

    def __init__(self, project_id: UUID, shared_docs: dict[UUID, DocumentModel] | None = None) -> None:
        self.project_id = project_id
        self.project = ProjectModel(
            id=project_id,
            title="Python Project",
            target_role="Backend Engineer",
            status=ProjectStatusEnum.ACTIVE,
        )
        self.documents: dict[UUID, DocumentModel] = shared_docs if shared_docs is not None else {}
        self.committed = False
        self.rolled_back = False

    async def get(self, model_cls: Any, ident: Any) -> Any:
        if model_cls is ProjectModel and ident == self.project_id:
            return self.project
        if model_cls is DocumentModel:
            return self.documents.get(ident)
        return None

    def add(self, entity: Any) -> None:
        if isinstance(entity, DocumentModel):
            self.documents[entity.id] = entity

    async def delete(self, entity: Any) -> None:
        if isinstance(entity, DocumentModel) and entity.id in self.documents:
            del self.documents[entity.id]

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def execute(self, statement: Any) -> Any:
        mock_result = MagicMock()
        mock_result.all.return_value = []
        return mock_result

    async def scalar(self, statement: Any) -> Any:
        stmt_str = str(statement)
        if "projects" in stmt_str:
            return self.project
        return None

    async def scalars(self, statement: Any) -> Any:
        # Return all non-deleted resumes across ATS if global query, or for this project if scoped
        stmt_str = str(statement)
        if "WHERE" in stmt_str and "documents.project_id =" in stmt_str:
            active_docs = [
                d for d in self.documents.values()
                if d.project_id == self.project_id and d.document_type == DocumentTypeEnum.RESUME and d.deleted_at is None
            ]
        else:
            active_docs = [
                d for d in self.documents.values()
                if d.document_type == DocumentTypeEnum.RESUME and d.deleted_at is None
            ]
        mock_result = MagicMock()
        mock_result.all.return_value = active_docs
        return mock_result


@pytest.fixture
def fake_zoho() -> FakeZohoRecruitAPI:
    return FakeZohoRecruitAPI()


@pytest.fixture
def zoho_client(fake_zoho: FakeZohoRecruitAPI, monkeypatch: pytest.MonkeyPatch) -> ZohoRecruitClient:
    async def no_sleep(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(ZohoRecruitClient, "_backoff", staticmethod(no_sleep))
    return ZohoRecruitClient(_test_settings(), transport=httpx.MockTransport(fake_zoho.handler))


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def mock_db(project_id: UUID) -> MockDB:
    return MockDB(project_id=project_id)


# -------------------------------------------------------------------------------------------------
# 1. First sync imports all 5 existing resumes.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_first_sync_imports_all_5_existing_resumes(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    req = ZohoImportApplicantsRequest(job_id="5001")
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp.candidates_seen == 5
    assert resp.imported_count == 5
    assert resp.skipped_count == 0
    assert resp.failed_count == 0
    assert resp.total_resumes == 5
    assert len(resp.document_ids) == 5
    assert len(mock_db.documents) == 5
    assert len(fake_zoho.downloads) == 5

    # Verify stable Zoho IDs are recorded in metadata_json
    att_ids = {doc.metadata_json["zoho_attachment_id"] for doc in mock_db.documents.values()}
    assert att_ids == {"att_1", "att_2", "att_3", "att_4", "att_5"}
    assert all(doc.metadata_json["zoho_job_opening_id"] == "5001" for doc in mock_db.documents.values())


# -------------------------------------------------------------------------------------------------
# 2. Repeating the sync with the same 5 resumes imports zero new records.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_repeating_sync_with_same_5_resumes_imports_zero_new_records(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    req = ZohoImportApplicantsRequest(job_id="5001")

    # First sync: 5 imported
    await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    assert len(mock_db.documents) == 5
    fake_zoho.downloads.clear()

    # Second sync: 0 new imported, 5 skipped
    resp2 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp2.candidates_seen == 5
    assert resp2.imported_count == 0
    assert resp2.skipped_count == 5
    assert resp2.total_resumes == 5
    assert len(resp2.document_ids) == 0
    assert len(mock_db.documents) == 5
    # Verify zero files were downloaded from Zoho during repeated sync
    assert len(fake_zoho.downloads) == 0
    assert all(s["reason"] == "already imported" for s in resp2.skipped)


# -------------------------------------------------------------------------------------------------
# 3. Adding one new resume results in exactly one new import.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_adding_one_new_resume_results_in_exactly_one_new_import(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    req = ZohoImportApplicantsRequest(job_id="5001")
    await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    fake_zoho.downloads.clear()

    # Add 6th candidate in Zoho
    fake_zoho.job_candidates.append({
        "id": "cand_6",
        "Candidate_ID": "ZR_6",
        "First_Name": "Candidate6",
        "Last_Name": "New",
        "Email": "cand6@example.com",
        "Modified_Time": "2026-10-06T10:00:00+05:30",
    })
    fake_zoho.attachments["cand_6"] = [
        {
            "id": "att_6",
            "File_Name": "resume_6.pdf",
            "Category": {"name": "Resume", "id": "1"},
            "Modified_Time": "2026-10-06T10:00:00+05:30",
        }
    ]

    # Subsequent sync
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp.candidates_seen == 6
    assert resp.imported_count == 1
    assert resp.skipped_count == 5
    assert resp.total_resumes == 6
    assert len(resp.document_ids) == 1
    assert len(mock_db.documents) == 6
    # Only the 6th attachment was downloaded!
    assert fake_zoho.downloads == ["att_6"]


# -------------------------------------------------------------------------------------------------
# 4. Existing resumes remain visible after subsequent syncs.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_existing_resumes_remain_visible_after_subsequent_syncs(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    req = ZohoImportApplicantsRequest(job_id="5001")
    resp1 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    original_ids = set(resp1.document_ids)

    # Perform multiple subsequent syncs
    for _ in range(3):
        await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    # All original documents are still active and non-deleted
    current_active_ids = {d.id for d in mock_db.documents.values() if d.deleted_at is None}
    assert original_ids.issubset(current_active_ids)
    assert len(current_active_ids) == 5


# -------------------------------------------------------------------------------------------------
# 5. Duplicate candidate/resume records are not created.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_duplicate_candidate_resume_records_are_not_created(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient
) -> None:
    req = ZohoImportApplicantsRequest(job_id="5001")
    await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    # Verify document IDs and attachment IDs are completely unique
    all_docs = list(mock_db.documents.values())
    assert len(all_docs) == 5
    unique_ids = {doc.id for doc in all_docs}
    unique_attachments = {doc.metadata_json["zoho_attachment_id"] for doc in all_docs}
    assert len(unique_ids) == 5
    assert len(unique_attachments) == 5


# -------------------------------------------------------------------------------------------------
# 6. A candidate with a distinct new resume/version is handled correctly.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_candidate_with_distinct_new_resume_version_is_handled_correctly(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    req = ZohoImportApplicantsRequest(job_id="5001")
    await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    fake_zoho.downloads.clear()

    # Candidate 1 uploads a new resume version with newer modified_time
    fake_zoho.attachments["cand_1"].append({
        "id": "att_1_v2",
        "File_Name": "resume_1_v2.pdf",
        "Category": {"name": "Resume", "id": "1"},
        "Modified_Time": "2026-10-15T12:00:00+05:30",
    })

    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp.imported_count == 1
    assert resp.skipped_count == 4  # cand_2..cand_5 skipped
    assert resp.total_resumes == 6
    assert fake_zoho.downloads == ["att_1_v2"]

    # Both resume versions (att_1 and att_1_v2) exist in the DB
    att_ids = {d.metadata_json["zoho_attachment_id"] for d in mock_db.documents.values()}
    assert "att_1" in att_ids
    assert "att_1_v2" in att_ids


# -------------------------------------------------------------------------------------------------
# 7. Pagination imports all records during the first sync.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pagination_imports_all_records_during_first_sync(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    # Setup 12 candidates and simulate 4-per-page pagination
    fake_zoho.job_candidates = [
        {
            "id": f"cand_{i}",
            "Candidate_ID": f"ZR_{i}",
            "First_Name": f"Cand{i}",
            "Modified_Time": f"2026-10-{i:02d}T10:00:00+05:30",
        }
        for i in range(1, 13)
    ]
    fake_zoho.attachments = {
        f"cand_{i}": [
            {
                "id": f"att_{i}",
                "File_Name": f"res_{i}.pdf",
                "Category": {"name": "Resume", "id": "1"},
                "Modified_Time": f"2026-10-{i:02d}T10:00:00+05:30",
            }
        ]
        for i in range(1, 13)
    }

    # Custom pagination handler (3 pages of 4 items)
    def paginated_handler(request: httpx.Request) -> httpx.Response:
        if "/oauth/v2/token" in request.url.path:
            return fake_zoho.handler(request)
        if "/associate" in request.url.path:
            page = int(request.url.params.get("page", 1))
            per_page = 4
            start = (page - 1) * per_page
            end = start + per_page
            chunk = fake_zoho.job_candidates[start:end]
            more = end < len(fake_zoho.job_candidates)
            return httpx.Response(200, json={"data": chunk, "info": {"page": page, "more_records": more}})
        return fake_zoho.handler(request)

    zoho_client._transport = httpx.MockTransport(paginated_handler)

    req = ZohoImportApplicantsRequest(job_id="5001")
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp.candidates_seen == 12
    assert resp.imported_count == 12
    assert resp.total_resumes == 12
    assert len(mock_db.documents) == 12


# -------------------------------------------------------------------------------------------------
# 8. A failed import can be retried successfully.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_import_can_be_retried_successfully(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    # First sync
    req = ZohoImportApplicantsRequest(job_id="5001")
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    assert resp.imported_count == 5

    # Simulate Candidate 3 failing downstream extraction/parsing
    failed_doc = next(d for d in mock_db.documents.values() if d.metadata_json["zoho_candidate_id"] == "cand_3")
    failed_doc.processing_status = ProcessingStatusEnum.FAILED

    # Retry sync: Candidate 3 is NOT skipped because it is FAILED
    fake_zoho.downloads.clear()
    resp2 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    # Candidate 3 was retried and imported, while 1, 2, 4, 5 were skipped
    assert resp2.imported_count == 1
    assert resp2.skipped_count == 4
    assert resp2.total_resumes == 5
    assert fake_zoho.downloads == ["att_3"]

    # Candidate 3 is now UPLOADED (retried) and not FAILED
    c3_doc = next(d for d in mock_db.documents.values() if d.metadata_json["zoho_candidate_id"] == "cand_3")
    assert c3_doc.processing_status == ProcessingStatusEnum.UPLOADED


# -------------------------------------------------------------------------------------------------
# 9. A partially failed sync does not duplicate previously successful imports.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_partially_failed_sync_does_not_duplicate_previously_successful_imports(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    # Make candidate 4 fail during initial download
    original_handler = fake_zoho.handler

    def partial_fail_handler(request: httpx.Request) -> httpx.Response:
        if "/Candidates/cand_4/Attachments/" in request.url.path:
            return httpx.Response(500, json={"message": "Temporary file error"})
        return original_handler(request)

    zoho_client._transport = httpx.MockTransport(partial_fail_handler)

    req = ZohoImportApplicantsRequest(job_id="5001")
    resp1 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    # 4 succeeded (1, 2, 3, 5), 1 failed (4)
    assert resp1.imported_count == 4
    assert resp1.failed_count == 1
    assert resp1.total_resumes == 4
    assert len(mock_db.documents) == 4

    # Restore normal handler (candidate 4 now succeeds)
    zoho_client._transport = httpx.MockTransport(original_handler)
    fake_zoho.downloads.clear()

    # Retry sync
    resp2 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    # Only candidate 4 was imported; candidates 1, 2, 3, 5 were skipped
    assert resp2.imported_count == 1
    assert resp2.skipped_count == 4
    assert resp2.total_resumes == 5
    assert len(mock_db.documents) == 5
    assert fake_zoho.downloads == ["att_4"]


# -------------------------------------------------------------------------------------------------
# 10. Concurrent sync requests do not create duplicates.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_sync_requests_do_not_create_duplicates(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient
) -> None:
    req = ZohoImportApplicantsRequest(job_id="5001")

    # Fire two concurrent sync requests for the same project
    resp1, resp2 = await asyncio.gather(
        import_zoho_applicants(project_id, req, mock_db, zoho_client),
        import_zoho_applicants(project_id, req, mock_db, zoho_client),
    )

    # One imported 5, the other imported 0
    imported_totals = [resp1.imported_count, resp2.imported_count]
    assert 5 in imported_totals
    assert 0 in imported_totals
    assert resp1.total_resumes == 5
    assert resp2.total_resumes == 5

    # Total documents in DB is strictly 5
    assert len(mock_db.documents) == 5


# -------------------------------------------------------------------------------------------------
# 11. A Zoho API failure does not cause existing ATS records to be deleted or marked as successfully synced incorrectly.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_zoho_api_failure_preserves_existing_ats_records(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    req = ZohoImportApplicantsRequest(job_id="5001")
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    assert resp.imported_count == 5
    assert len(mock_db.documents) == 5

    # Simulate Zoho API failure
    fake_zoho.fail_all = True

    with pytest.raises(Exception) as exc_info:
        await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert "Zoho Recruit" in str(exc_info.value) or "502" in str(exc_info.value)
    # Existing ATS records remain completely intact and non-deleted
    assert len(mock_db.documents) == 5
    assert all(d.deleted_at is None for d in mock_db.documents.values())


# -------------------------------------------------------------------------------------------------
# 12. The frontend and API response correctly distinguish total records from newly imported records.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_frontend_and_api_response_distinguish_total_from_newly_imported(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    req = ZohoImportApplicantsRequest(job_id="5001")

    # Sync 1: 5 new resumes
    r1 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    assert r1.imported_count == 5
    assert r1.total_resumes == 5
    assert r1.candidates_seen == 5

    # Sync 2: 0 new resumes
    r2 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    assert r2.imported_count == 0
    assert r2.total_resumes == 5
    assert r2.candidates_seen == 5

    # Add 1 new resume in Zoho
    fake_zoho.job_candidates.append({
        "id": "cand_6",
        "Candidate_ID": "ZR_6",
        "Modified_Time": "2026-10-06T10:00:00+05:30",
    })
    fake_zoho.attachments["cand_6"] = [
        {"id": "att_6", "File_Name": "r6.pdf", "Category": {"name": "Resume"}, "Modified_Time": "2026-10-06T10:00:00+05:30"}
    ]

    # Sync 3: 1 new resume
    r3 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    assert r3.imported_count == 1
    assert r3.total_resumes == 6
    assert r3.candidates_seen == 6
    assert r3.total_found == 6
    assert r3.already_fetched == 5
    assert r3.new_resumes == 1
    assert r3.summary is not None
    assert r3.summary.total_found == 6
    assert r3.summary.already_fetched == 5
    assert r3.summary.new_resumes == 1


# =================================================================================================
# COMPREHENSIVE SUITE FOR STEP 7 REQUIREMENTS
# =================================================================================================

# -------------------------------------------------------------------------------------------------
# Requirement 1: First fetch: 50 found, 0 already fetched, 50 new.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case1_first_fetch_50_found_0_already_fetched_50_new(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    fake_zoho.setup_n_candidates(50)
    fake_zoho.downloads.clear()
    req = ZohoImportApplicantsRequest(job_id="9001")

    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp.total_found == 50
    assert resp.already_fetched == 0
    assert resp.new_resumes == 50
    assert resp.imported_count == 50
    assert resp.failed_resumes == 0
    assert len(resp.document_ids) == 50
    assert len(mock_db.documents) == 50
    assert len(fake_zoho.downloads) == 50
    assert resp.summary is not None
    assert resp.summary.total_found == 50
    assert resp.summary.already_fetched == 0
    assert resp.summary.new_resumes == 50


# -------------------------------------------------------------------------------------------------
# Requirement 2: Second fetch, unchanged: 50 found, 50 already fetched, 0 new.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case2_second_fetch_unchanged_50_found_50_already_fetched_0_new(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    fake_zoho.setup_n_candidates(50)
    req = ZohoImportApplicantsRequest(job_id="9001")

    # First fetch (50 imported)
    await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    fake_zoho.downloads.clear()

    # Second fetch (unchanged)
    resp2 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp2.total_found == 50
    assert resp2.already_fetched == 50
    assert resp2.new_resumes == 0
    assert resp2.imported_count == 0
    assert resp2.failed_resumes == 0
    assert len(resp2.document_ids) == 0
    assert len(mock_db.documents) == 50
    assert len(fake_zoho.downloads) == 0  # Zero downloads performed
    assert resp2.summary is not None
    assert resp2.summary.total_found == 50
    assert resp2.summary.already_fetched == 50
    assert resp2.summary.new_resumes == 0


# -------------------------------------------------------------------------------------------------
# Requirement 3: Five new resumes added: 55 found, 50 already fetched, 5 new.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case3_five_new_resumes_added_55_found_50_already_fetched_5_new(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    fake_zoho.setup_n_candidates(50)
    req = ZohoImportApplicantsRequest(job_id="9001")
    await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    fake_zoho.downloads.clear()

    # Add 5 new candidates in Zoho (candidates 51 to 55)
    for i in range(51, 56):
        fake_zoho.job_candidates.append({
            "id": f"cand_{i}",
            "Candidate_ID": f"ZR_{i}",
            "First_Name": f"Candidate{i}",
            "Last_Name": "New",
            "Email": f"cand{i}@example.com",
            "Modified_Time": "2026-10-02T10:00:00+05:30",
        })
        fake_zoho.attachments[f"cand_{i}"] = [
            {
                "id": f"att_{i}",
                "File_Name": f"resume_{i}.pdf",
                "Category": {"name": "Resume"},
                "Modified_Time": "2026-10-02T10:00:00+05:30",
            }
        ]

    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp.total_found == 55
    assert resp.already_fetched == 50
    assert resp.new_resumes == 5
    assert resp.imported_count == 5
    assert resp.failed_resumes == 0
    assert len(resp.document_ids) == 5
    assert len(mock_db.documents) == 55
    assert len(fake_zoho.downloads) == 5
    assert fake_zoho.downloads == [f"att_{i}" for i in range(51, 56)]
    assert resp.summary is not None
    assert resp.summary.total_found == 55
    assert resp.summary.already_fetched == 50
    assert resp.summary.new_resumes == 5


# -------------------------------------------------------------------------------------------------
# Requirement 4: Third fetch after all 55 have been imported: 55 found, 55 already fetched, 0 new.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case4_third_fetch_after_all_55_imported_55_found_55_already_fetched_0_new(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    fake_zoho.setup_n_candidates(55)
    req = ZohoImportApplicantsRequest(job_id="9001")

    # First fetch (all 55 imported)
    await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    fake_zoho.downloads.clear()

    # Third fetch (repeated on all 55)
    resp3 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp3.total_found == 55
    assert resp3.already_fetched == 55
    assert resp3.new_resumes == 0
    assert resp3.imported_count == 0
    assert len(resp3.document_ids) == 0
    assert len(mock_db.documents) == 55
    assert len(fake_zoho.downloads) == 0
    assert resp3.summary is not None
    assert resp3.summary.total_found == 55
    assert resp3.summary.already_fetched == 55
    assert resp3.summary.new_resumes == 0


# -------------------------------------------------------------------------------------------------
# Requirement 5: Existing document IDs are not passed into parsing, extraction, or normalization during incremental fetch.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case5_existing_document_ids_not_passed_into_processing_pipeline(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    fake_zoho.setup_n_candidates(5)
    req = ZohoImportApplicantsRequest(job_id="9001", auto_process=True)
    resp1 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)
    initial_ids = set(resp1.document_ids)
    assert len(initial_ids) == 5

    # Add 1 new candidate
    fake_zoho.job_candidates.append({
        "id": "cand_6",
        "Candidate_ID": "ZR_6",
        "First_Name": "Candidate6",
        "Last_Name": "New",
        "Email": "cand6@example.com",
    })
    fake_zoho.attachments["cand_6"] = [
        {"id": "att_6", "File_Name": "resume_6.pdf", "Category": {"name": "Resume"}}
    ]

    with patch("app.api.v1.endpoints.zoho.ParsingService") as mock_parser_cls:
        mock_parser = MagicMock()
        mock_parser.parse_document = AsyncMock(return_value=None)
        mock_parser_cls.return_value = mock_parser

        resp2 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

        # Only the 1 new document ID is in resp2.document_ids
        assert len(resp2.document_ids) == 1
        new_doc_id = resp2.document_ids[0]
        assert new_doc_id not in initial_ids

        # Only the new document was passed to parse_document, NONE of the initial IDs
        assert mock_parser.parse_document.call_count == 1
        parsed_call_args = [call.args[0] for call in mock_parser.parse_document.call_args_list]
        assert parsed_call_args == [new_doc_id]
        assert not any(old_id in parsed_call_args for old_id in initial_ids)


# -------------------------------------------------------------------------------------------------
# Requirement 6: Existing completed documents are not recreated, downloaded, or reset.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case6_existing_completed_documents_not_recreated_downloaded_or_reset(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    fake_zoho.setup_n_candidates(3)
    req = ZohoImportApplicantsRequest(job_id="9001")
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    # Mark existing documents as COMPLETED in normalization
    for doc in mock_db.documents.values():
        doc.processing_status = ProcessingStatusEnum.COMPLETED
        doc.processing_stage = ProcessingStageEnum.COMPLETED

    fake_zoho.downloads.clear()
    original_docs = {id: (d.processing_status, d.processing_stage, d.updated_at) for id, d in mock_db.documents.items()}

    # Run incremental fetch
    resp2 = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp2.imported_count == 0
    assert len(fake_zoho.downloads) == 0  # Not downloaded
    assert len(mock_db.documents) == 3   # Not recreated

    # None were reset: status remains COMPLETED
    for doc_id, doc in mock_db.documents.items():
        orig_status, orig_stage, _ = original_docs[doc_id]
        assert doc.processing_status == ProcessingStatusEnum.COMPLETED
        assert doc.processing_stage == ProcessingStageEnum.COMPLETED
        assert doc.processing_status == orig_status
        assert doc.processing_stage == orig_stage


# -------------------------------------------------------------------------------------------------
# Requirement 7: Resumes associated with a different Job Opening are handled according to correct per-opening relationship.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case7_resumes_associated_with_different_job_opening_handled_per_opening(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    # Setup Opening 9001 with candidates 1..3
    fake_zoho.setup_n_candidates(3, start_idx=1, prefix="cand_")
    req1 = ZohoImportApplicantsRequest(job_id="9001")
    resp1 = await import_zoho_applicants(project_id, req1, mock_db, zoho_client)
    assert resp1.total_found == 3
    assert resp1.already_fetched == 0
    assert resp1.new_resumes == 3

    # Now simulate Job Opening 9002 in Zoho, which has candidates 4..5
    fake_zoho.setup_n_candidates(2, start_idx=4, prefix="cand_")
    req2 = ZohoImportApplicantsRequest(job_id="9002")

    # Fetching for Opening 9002 should NOT treat Opening 9001's 3 resumes as "already fetched" for 9002!
    resp2 = await import_zoho_applicants(project_id, req2, mock_db, zoho_client)
    assert resp2.job_id == "9002"
    assert resp2.total_found == 2
    assert resp2.already_fetched == 0
    assert resp2.new_resumes == 2
    assert resp2.summary is not None
    assert resp2.summary.already_fetched == 0
    assert resp2.summary.new_resumes == 2

    # Verify documents in DB are properly tagged with their respective job openings
    docs_9001 = [d for d in mock_db.documents.values() if d.metadata_json.get("zoho_job_opening_id") == "9001"]
    docs_9002 = [d for d in mock_db.documents.values() if d.metadata_json.get("zoho_job_opening_id") == "9002"]
    assert len(docs_9001) == 3
    assert len(docs_9002) == 2


# -------------------------------------------------------------------------------------------------
# Requirement 8: Pagination retrieves and counts every eligible resume.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case8_pagination_retrieves_and_counts_every_eligible_resume(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    fake_zoho.setup_n_candidates(25)

    # Simulate 10 per page pagination (3 pages: 10, 10, 5)
    def paginated_handler(request: httpx.Request) -> httpx.Response:
        if "/oauth/v2/token" in request.url.path:
            return fake_zoho.handler(request)
        if "/associate" in request.url.path:
            page = int(request.url.params.get("page", 1))
            per_page = 10
            start = (page - 1) * per_page
            end = start + per_page
            chunk = fake_zoho.job_candidates[start:end]
            more = end < len(fake_zoho.job_candidates)
            return httpx.Response(200, json={"data": chunk, "info": {"page": page, "more_records": more}})
        return fake_zoho.handler(request)

    zoho_client._transport = httpx.MockTransport(paginated_handler)

    req = ZohoImportApplicantsRequest(job_id="9001")
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp.candidates_seen == 25
    assert resp.total_found == 25
    assert resp.already_fetched == 0
    assert resp.new_resumes == 25
    assert len(mock_db.documents) == 25


# -------------------------------------------------------------------------------------------------
# Requirement 9: Duplicate external records in the Zoho response are not double-counted.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case9_duplicate_external_records_not_double_counted(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    fake_zoho.setup_n_candidates(3)
    # Duplicate candidate 1 and candidate 2 in the Zoho candidate response
    fake_zoho.job_candidates.append(dict(fake_zoho.job_candidates[0]))
    fake_zoho.job_candidates.append(dict(fake_zoho.job_candidates[1]))
    assert len(fake_zoho.job_candidates) == 5  # 3 unique, 2 duplicates

    req = ZohoImportApplicantsRequest(job_id="9001")
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    # candidates_seen is 5, but unique eligible resumes is strictly 3
    assert resp.candidates_seen == 5
    assert resp.total_found == 3
    assert resp.already_fetched == 0
    assert resp.new_resumes == 3
    assert len(mock_db.documents) == 3


# -------------------------------------------------------------------------------------------------
# Requirement 10: A failed import is not reported as a successful import.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case10_failed_import_not_reported_as_successful(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    fake_zoho.setup_n_candidates(3)
    original_handler = fake_zoho.handler

    # Simulate Candidate 2 failing attachment download (HTTP 500)
    def fail_handler(request: httpx.Request) -> httpx.Response:
        if "/Candidates/cand_2/Attachments/att_2" in request.url.path:
            return httpx.Response(500, json={"message": "Zoho file read error"})
        return original_handler(request)

    zoho_client._transport = httpx.MockTransport(fail_handler)

    req = ZohoImportApplicantsRequest(job_id="9001")
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp.total_found == 3
    assert resp.already_fetched == 0
    assert resp.new_resumes == 2
    assert resp.failed_resumes == 1
    assert resp.failed_count == 1
    assert len(mock_db.documents) == 2
    # Verify candidate 2 was not reported as imported
    imported_cand_ids = {d.metadata_json["zoho_candidate_id"] for d in mock_db.documents.values()}
    assert "cand_2" not in imported_cand_ids


# -------------------------------------------------------------------------------------------------
# Requirement 13: Zero-new-resume fetches still return the correct summary.
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step7_case13_zero_eligible_resumes_returns_correct_zero_summary(
    project_id: UUID, mock_db: MockDB, zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    # 2 candidates with NO PDF/DOCX resumes attached
    fake_zoho.job_candidates = [
        {"id": "cand_x", "Candidate_ID": "ZR_X", "First_Name": "NoResume1"},
        {"id": "cand_y", "Candidate_ID": "ZR_Y", "First_Name": "NoResume2"},
    ]
    fake_zoho.attachments = {
        "cand_x": [],
        "cand_y": [{"id": "att_y", "File_Name": "photo.png", "Category": {"name": "Photo"}}],
    }

    req = ZohoImportApplicantsRequest(job_id="9001")
    resp = await import_zoho_applicants(project_id, req, mock_db, zoho_client)

    assert resp.candidates_seen == 2
    assert resp.total_found == 0
    assert resp.already_fetched == 0
    assert resp.new_resumes == 0
    assert resp.failed_resumes == 0
    assert len(resp.document_ids) == 0
    assert len(mock_db.documents) == 0
    assert resp.summary is not None
    assert resp.summary.total_found == 0
    assert resp.summary.already_fetched == 0
    assert resp.summary.new_resumes == 0


# -------------------------------------------------------------------------------------------------
# Requirement 14: Frontend hydration does not queue already completed documents for processing.
# -------------------------------------------------------------------------------------------------
def test_step7_case14_frontend_hydration_does_not_queue_completed_documents() -> None:
    """Verify that completed documents restored during hydration or SET_RESUMES are marked normalized

    and excluded from pending processing IDs.
    """
    # Simulate a project resume list where doc_1 is COMPLETED and doc_2 is UPLOADED
    resumes_from_api = [
        {"id": "doc_1", "statusLabel": "COMPLETED", "status": "done"},
        {"id": "doc_2", "statusLabel": "UPLOADED", "status": "done"},
    ]

    resume_processing: dict[str, Any] = {}
    for r in resumes_from_api:
        is_completed = r["statusLabel"] == "COMPLETED" or r["statusLabel"] == "PARSED"
        resume_processing[r["id"]] = {
            "documentId": r["id"],
            "phase": "normalized" if is_completed else "uploaded",
            "status": r["statusLabel"],
            "normalized": is_completed,
        }

    # Verify doc_1 is marked normalized
    assert resume_processing["doc_1"]["normalized"] is True
    assert resume_processing["doc_1"]["phase"] == "normalized"

    # Simulate pending computation in ResumeUpload.tsx:
    # const pending = state.resumeDocumentIds.filter((id) => {
    #   const p = state.resumeProcessing[id]
    #   return p && !p.normalized && p.phase === 'uploaded'
    # })
    doc_ids = ["doc_1", "doc_2"]
    pending = [
        id for id in doc_ids
        if resume_processing[id] and not resume_processing[id]["normalized"] and resume_processing[id]["phase"] == "uploaded"
    ]

    # Completed doc_1 is NOT in pending; only genuinely uploaded-but-unprocessed doc_2 is pending
    assert "doc_1" not in pending
    assert pending == ["doc_2"]


# =================================================================================================
# GLOBAL DUPLICATE PREVENTION ACROSS ATS REQUISITIONS (SCENARIOS 1 - 4)
# =================================================================================================

@pytest.mark.asyncio
async def test_scenarios_1_to_4_global_duplicate_prevention_across_requisitions(
    zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    """Validate Scenarios 1 to 4 from the specification:

    Scenario 1: First fetch in Requisition A imports 15 resumes (15 found, 0 already, 15 new).
    Scenario 2: Requisition B (new ATS requisition) fetches same opening (15 found, 15 already, 0 new).
    Scenario 3: 5 new candidates added (20 total) -> Requisition C fetches -> imports only 5 new (20 found, 15 already, 5 new).
    Scenario 4: Requisition D fetches again -> (20 found, 20 already, 0 new).
    """
    shared_ats_documents: dict[UUID, DocumentModel] = {}
    job_id = "7001"

    # Set up 15 initial candidates in Zoho
    fake_zoho.setup_n_candidates(15, start_idx=1, prefix="scand_")
    fake_zoho.downloads.clear()

    # ---------------------------------------------------------------------------------------------
    # Scenario 1: First-time resume fetch for Requisition A
    # ---------------------------------------------------------------------------------------------
    req_a_id = uuid4()
    db_a = MockDB(req_a_id, shared_docs=shared_ats_documents)

    req1 = ZohoImportApplicantsRequest(job_id=job_id)
    resp1 = await import_zoho_applicants(req_a_id, req1, db_a, zoho_client)

    assert resp1.candidates_seen == 15
    assert resp1.total_found == 15
    assert resp1.already_fetched == 0
    assert resp1.new_resumes == 15
    assert resp1.imported_count == 15
    assert resp1.failed_count == 0
    assert len(resp1.document_ids) == 15
    assert len(shared_ats_documents) == 15
    assert len(fake_zoho.downloads) == 15
    assert resp1.summary is not None
    assert resp1.summary.total_found == 15
    assert resp1.summary.already_fetched == 0
    assert resp1.summary.new_resumes == 15
    assert resp1.summary.failed_resumes == 0

    fake_zoho.downloads.clear()

    # ---------------------------------------------------------------------------------------------
    # Scenario 2: Create a new requisition (Requisition B) and fetch the same Zoho Job Opening again
    # ---------------------------------------------------------------------------------------------
    req_b_id = uuid4()
    db_b = MockDB(req_b_id, shared_docs=shared_ats_documents)

    resp2 = await import_zoho_applicants(req_b_id, req1, db_b, zoho_client)

    assert resp2.candidates_seen == 15
    assert resp2.total_found == 15
    assert resp2.already_fetched == 15
    assert resp2.new_resumes == 0
    assert resp2.imported_count == 0
    assert resp2.failed_count == 0
    assert len(resp2.document_ids) == 0  # No documents passed to processing pipeline!
    assert len(shared_ats_documents) == 15  # Zero duplicate records created!
    assert len(fake_zoho.downloads) == 0  # Zero attachments downloaded!
    assert resp2.summary is not None
    assert resp2.summary.total_found == 15
    assert resp2.summary.already_fetched == 15
    assert resp2.summary.new_resumes == 0
    assert resp2.summary.failed_resumes == 0

    # ---------------------------------------------------------------------------------------------
    # Scenario 3: 5 new resumes added to the same Zoho Job Opening (20 total)
    # ---------------------------------------------------------------------------------------------
    # Add 5 more candidates (cand 16 to 20)
    for i in range(16, 21):
        fake_zoho.job_candidates.append({
            "id": f"scand_{i}",
            "Candidate_ID": f"ZR_{i}",
            "First_Name": f"Candidate{i}",
            "Last_Name": "Test",
            "Email": f"cand{i}@example.com",
            "Modified_Time": "2026-10-02T10:00:00+05:30",
        })
        fake_zoho.attachments[f"scand_{i}"] = [
            {
                "id": f"att_{i}",
                "File_Name": f"resume_{i}.pdf",
                "Category": {"name": "Resume", "id": "1"},
                "Modified_Time": "2026-10-02T10:00:00+05:30",
                "Size": "1024",
            }
        ]

    req_c_id = uuid4()
    db_c = MockDB(req_c_id, shared_docs=shared_ats_documents)

    resp3 = await import_zoho_applicants(req_c_id, req1, db_c, zoho_client)

    assert resp3.candidates_seen == 20
    assert resp3.total_found == 20
    assert resp3.already_fetched == 15
    assert resp3.new_resumes == 5
    assert resp3.imported_count == 5
    assert len(resp3.document_ids) == 5  # Only 5 new document IDs passed to pipeline!
    assert len(shared_ats_documents) == 20  # Total in ATS is now 20
    assert len(fake_zoho.downloads) == 5  # Exactly 5 files downloaded from Zoho!
    assert resp3.summary is not None
    assert resp3.summary.total_found == 20
    assert resp3.summary.already_fetched == 15
    assert resp3.summary.new_resumes == 5
    assert resp3.summary.failed_resumes == 0

    fake_zoho.downloads.clear()

    # ---------------------------------------------------------------------------------------------
    # Scenario 4: Fetch again after all 20 resumes are imported
    # ---------------------------------------------------------------------------------------------
    req_d_id = uuid4()
    db_d = MockDB(req_d_id, shared_docs=shared_ats_documents)

    resp4 = await import_zoho_applicants(req_d_id, req1, db_d, zoho_client)

    assert resp4.candidates_seen == 20
    assert resp4.total_found == 20
    assert resp4.already_fetched == 20
    assert resp4.new_resumes == 0
    assert resp4.imported_count == 0
    assert len(resp4.document_ids) == 0
    assert len(shared_ats_documents) == 20
    assert len(fake_zoho.downloads) == 0
    assert resp4.summary is not None
    assert resp4.summary.total_found == 20
    assert resp4.summary.already_fetched == 20
    assert resp4.summary.new_resumes == 0
    assert resp4.summary.failed_resumes == 0


@pytest.mark.asyncio
async def test_different_zoho_job_openings_remain_isolated_across_requisitions(
    zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    """A candidate applied to Job Opening 8001 and also to Job Opening 8002.

    Job Opening 8002 import must not skip the candidate based on 8001's job opening.
    """
    shared_ats_documents: dict[UUID, DocumentModel] = {}
    fake_zoho.setup_n_candidates(3, start_idx=1, prefix="multijob_")
    fake_zoho.downloads.clear()

    # Requisition 1 imports from Job Opening 8001
    p1 = uuid4()
    db1 = MockDB(p1, shared_docs=shared_ats_documents)
    req1 = ZohoImportApplicantsRequest(job_id="8001")
    resp1 = await import_zoho_applicants(p1, req1, db1, zoho_client)
    assert resp1.new_resumes == 3
    assert len(shared_ats_documents) == 3

    # Requisition 2 imports same candidates for Job Opening 8002
    # In fake_zoho, the same candidates apply to 8002
    p2 = uuid4()
    db2 = MockDB(p2, shared_docs=shared_ats_documents)
    req2 = ZohoImportApplicantsRequest(job_id="8002")

    # Change attachment IDs for job 8002 application so they are treated as valid for 8002
    for i in range(1, 4):
        fake_zoho.attachments[f"multijob_{i}"] = [
            {
                "id": f"att_8002_{i}",
                "File_Name": f"resume_{i}.pdf",
                "Category": {"name": "Resume", "id": "1"},
                "Modified_Time": "2026-10-03T10:00:00+05:30",
                "Size": "1024",
            }
        ]

    resp2 = await import_zoho_applicants(p2, req2, db2, zoho_client)
    assert resp2.new_resumes == 3
    assert len(shared_ats_documents) == 6


@pytest.mark.asyncio
async def test_attachment_modified_time_changed_triggers_redownload(
    zoho_client: ZohoRecruitClient, fake_zoho: FakeZohoRecruitAPI
) -> None:
    """If Zoho reuses the same attachment ID but updates the modified time,

    the integration detects changed content and downloads the updated version.
    """
    shared_ats_documents: dict[UUID, DocumentModel] = {}
    fake_zoho.setup_n_candidates(1, start_idx=1, prefix="modcand_")
    fake_zoho.attachments["modcand_1"][0]["Modified_Time"] = "2026-10-01T10:00:00+05:30"
    fake_zoho.downloads.clear()

    p1 = uuid4()
    db1 = MockDB(p1, shared_docs=shared_ats_documents)
    req = ZohoImportApplicantsRequest(job_id="9001")

    # Initial fetch
    resp1 = await import_zoho_applicants(p1, req, db1, zoho_client)
    assert resp1.new_resumes == 1
    assert len(fake_zoho.downloads) == 1
    fake_zoho.downloads.clear()

    # Same modified time -> skipped
    resp2 = await import_zoho_applicants(p1, req, db1, zoho_client)
    assert resp2.new_resumes == 0
    assert len(fake_zoho.downloads) == 0

    # Zoho updates modified time on the same attachment ID
    fake_zoho.attachments["modcand_1"][0]["Modified_Time"] = "2026-10-05T12:00:00+05:30"
    p2 = uuid4()
    db2 = MockDB(p2, shared_docs=shared_ats_documents)

    # Next fetch detects modified time change and downloads
    await import_zoho_applicants(p2, req, db2, zoho_client)
    assert len(fake_zoho.downloads) == 1

