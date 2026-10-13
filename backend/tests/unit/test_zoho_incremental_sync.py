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
        self.job_candidates = [
            {
                "id": f"cand_{i}",
                "Candidate_ID": f"ZR_{i}",
                "First_Name": f"Candidate{i}",
                "Last_Name": "Test",
                "Email": f"cand{i}@example.com",
                "Mobile": f"+91987654321{i}",
                "Source": "Website",
                "Modified_Time": f"2026-10-0{i}T10:00:00+05:30",
            }
            for i in range(1, 6)
        ]
        self.attachments = {
            f"cand_{i}": [
                {
                    "id": f"att_{i}",
                    "File_Name": f"resume_{i}.pdf",
                    "Category": {"name": "Resume", "id": "1"},
                    "Modified_Time": f"2026-10-0{i}T10:00:00+05:30",
                    "Size": "1024",
                }
            ]
            for i in range(1, 6)
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
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": parts[1],
                            "Posting_Title": "Senior Backend Engineer",
                            "Job_Opening_ID": "JOB_001",
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

    def __init__(self, project_id: UUID) -> None:
        self.project_id = project_id
        self.project = ProjectModel(
            id=project_id,
            title="Python Project",
            target_role="Backend Engineer",
            status=ProjectStatusEnum.ACTIVE,
        )
        self.documents: dict[UUID, DocumentModel] = {}
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
        # Return all non-deleted resumes for this project
        active_docs = [
            d for d in self.documents.values()
            if d.project_id == self.project_id and d.document_type == DocumentTypeEnum.RESUME and d.deleted_at is None
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
