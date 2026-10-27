import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.zoho import _is_db_timeout, import_zoho_applicants
from app.core.config import Settings
from app.models.document import (
    DocumentModel,
    DocumentTypeEnum,
    ProcessingStageEnum,
    ProcessingStatusEnum,
)
from app.models.project import ProjectModel, ProjectStatusEnum
from app.schemas.zoho import ZohoImportApplicantsRequest
from app.services.zoho_recruit_service import (
    ZohoCandidateResume,
    ZohoJobOpening,
    ZohoRecruitClient,
)


def _test_settings(**overrides: Any) -> Settings:
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


class ResilientMockDB:
    """In-memory mock DB with configurable timeout errors and document store."""

    def __init__(
        self,
        project_id: UUID,
        shared_docs: dict[UUID, DocumentModel] | None = None,
        *,
        timeout_stage: str | None = None,
    ) -> None:
        self.project_id = project_id
        self.project = ProjectModel(
            id=project_id,
            title="Test Project",
            target_role="Software Engineer",
            status=ProjectStatusEnum.ACTIVE,
        )
        self.documents: dict[UUID, DocumentModel] = shared_docs if shared_docs is not None else {}
        self.timeout_stage = timeout_stage  # "pre_sync", "hash_lookup", "commit", or None
        self.committed = False
        self.rolled_back = False
        self.deleted_doc_ids: list[UUID] = []
        self.queries_executed: list[str] = []

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
        if isinstance(entity, DocumentModel):
            self.deleted_doc_ids.append(entity.id)
            self.documents.pop(entity.id, None)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        if self.timeout_stage == "commit":
            raise TimeoutError("Simulated database commit timeout")
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def scalar(self, statement: Any) -> Any:
        stmt_str = str(statement)
        if "projects" in stmt_str:
            return self.project
        return None

    async def scalars(self, statement: Any) -> Any:
        stmt_str = str(statement)
        self.queries_executed.append(stmt_str)

        # 1. Simulate pre_sync query timeout
        if self.timeout_stage == "pre_sync" and "documents.deleted_at IS NULL" in stmt_str and "documents.file_hash IN" not in stmt_str:
            raise TimeoutError("Simulated asyncpg query timeout on existing documents query")

        # 2. Simulate batch hash lookup timeout
        if self.timeout_stage == "hash_lookup" and "documents.file_hash IN" in stmt_str:
            raise TimeoutError("Simulated asyncpg query timeout on batch hash lookup")

        # 3. Batch hash query
        if "documents.file_hash IN" in stmt_str or ("documents.file_hash" in stmt_str and "SELECT documents.file_hash" in stmt_str):
            hashes = [
                d.file_hash for d in self.documents.values()
                if d.document_type == DocumentTypeEnum.RESUME and d.deleted_at is None and d.file_hash
            ]
            mock_res = MagicMock()
            mock_res.all.return_value = hashes
            return mock_res

        # 4. Zoho documents query
        active_docs = [
            d for d in self.documents.values()
            if d.document_type == DocumentTypeEnum.RESUME and d.deleted_at is None
        ]
        mock_res = MagicMock()
        mock_res.all.return_value = active_docs
        return mock_res


class MockZohoAPI:
    """Mock Zoho API transport returning mock job openings and candidate resumes."""

    def __init__(self, candidates_count: int = 2) -> None:
        self.candidates_count = candidates_count
        self.downloads: list[str] = []
        self.current_job_id = "default"

    def handler(self, request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        if url_path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})

        parts = url_path.split("/recruit/v2/")[1].split("/")

        # JobOpenings/{id}
        if len(parts) == 2 and parts[0] in ("JobOpenings", "Job_Openings"):
            job_id = parts[1]
            self.current_job_id = job_id
            return httpx.Response(200, json={
                "data": [{
                    "id": job_id,
                    "Posting_Title": "Senior Backend Engineer",
                    "Job_Opening_ID": f"JOB_{job_id}",
                    "Job_Description": "Expert backend developer.",
                    "Required_Skills": "Python, PostgreSQL",
                    "Job_Opening_Status": "Open",
                    "Modified_Time": "2026-10-01T10:00:00+05:30",
                    "No_of_Candidates_Associated": self.candidates_count,
                }]
            })

        # Job_Openings/{id}/associate
        if len(parts) == 3 and parts[0] in ("Job_Openings", "JobOpenings") and parts[2] == "associate":
            self.current_job_id = parts[1]
            candidates = [
                {
                    "id": f"cand_{i}",
                    "Candidate_ID": f"ZR_{i}",
                    "First_Name": f"FirstName{i}",
                    "Last_Name": f"LastName{i}",
                    "Email": f"applicant_{i}@example.com",
                    "Mobile": f"+9198765432{i:02d}",
                    "Source": "Zoho Portal",
                    "Modified_Time": "2026-10-01T12:00:00+05:30",
                }
                for i in range(1, self.candidates_count + 1)
            ]
            return httpx.Response(200, json={"data": candidates, "info": {"page": 1, "more_records": False}})

        # Candidates/{id}/Attachments
        if len(parts) == 3 and parts[0] == "Candidates" and parts[2] == "Attachments":
            cand_id = parts[1]
            return httpx.Response(200, json={
                "data": [{
                    "id": f"att_{self.current_job_id}_{cand_id}",
                    "File_Name": f"resume_{cand_id}.pdf",
                    "Category": {"name": "Resume", "id": "1"},
                    "Modified_Time": "2026-10-01T12:00:00+05:30",
                    "Size": "2048",
                }],
                "info": {"more_records": False},
            })

        # Candidates/{id}/Attachments/{att_id} (Download)
        if len(parts) == 4 and parts[0] == "Candidates" and parts[2] == "Attachments":
            att_id = parts[3]
            self.downloads.append(att_id)
            content = f"Content for resume attachment {att_id}".encode("utf-8")
            return httpx.Response(
                200,
                content=content,
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Disposition": f'attachment; filename="resume_{att_id}.pdf"',
                },
            )

        return httpx.Response(404, json={"code": "NOT_FOUND"})


# -------------------------------------------------------------------------------------------------
# Test 1: Helper _is_db_timeout correctly identifies timeouts across exception hierarchies
# -------------------------------------------------------------------------------------------------
def test_is_db_timeout_detection() -> None:
    assert _is_db_timeout(TimeoutError("Standard timeout"))
    assert _is_db_timeout(asyncio.TimeoutError())

    # Simulated asyncpg TimeoutError
    class AsyncpgTimeoutError(Exception):
        pass

    assert _is_db_timeout(AsyncpgTimeoutError("asyncpg timeout exceeded"))

    # Chained exception
    chained = RuntimeError("Query execution failed")
    chained.__cause__ = TimeoutError("Inner socket timeout")
    assert _is_db_timeout(chained)

    # Non-timeout exceptions
    assert not _is_db_timeout(ValueError("Invalid argument"))
    assert not _is_db_timeout(KeyError("missing_key"))


# -------------------------------------------------------------------------------------------------
# Test 2: Pre-sync database query timeout returns HTTP 504 and does not corrupt state
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pre_sync_query_timeout_raises_http_504() -> None:
    proj_id = uuid4()
    mock_db = ResilientMockDB(proj_id, timeout_stage="pre_sync")
    api = MockZohoAPI(candidates_count=2)
    client = ZohoRecruitClient(_test_settings(), transport=httpx.MockTransport(api.handler))
    req = ZohoImportApplicantsRequest(job_id="7001")

    with pytest.raises(HTTPException) as exc_info:
        await import_zoho_applicants(proj_id, req, mock_db, client)

    assert exc_info.value.status_code == 504
    assert "Database query timed out while preparing Zoho import" in exc_info.value.detail
    # No files downloaded and no documents created
    assert len(api.downloads) == 0
    assert len(mock_db.documents) == 0


# -------------------------------------------------------------------------------------------------
# Test 3: Batch hash lookup timeout returns HTTP 504 and cleans up temporary files
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_batch_hash_lookup_timeout_raises_http_504() -> None:
    proj_id = uuid4()
    mock_db = ResilientMockDB(proj_id, timeout_stage="hash_lookup")
    api = MockZohoAPI(candidates_count=2)
    client = ZohoRecruitClient(_test_settings(), transport=httpx.MockTransport(api.handler))
    req = ZohoImportApplicantsRequest(job_id="7001")

    with pytest.raises(HTTPException) as exc_info:
        await import_zoho_applicants(proj_id, req, mock_db, client)

    assert exc_info.value.status_code == 504
    assert "Database query timed out during duplicate detection" in exc_info.value.detail
    assert len(mock_db.documents) == 0


# -------------------------------------------------------------------------------------------------
# Test 4: Commit timeout returns HTTP 504, triggers rollback, and cleans up storage files
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_commit_timeout_raises_http_504_and_rolls_back() -> None:
    proj_id = uuid4()
    mock_db = ResilientMockDB(proj_id, timeout_stage="commit")
    api = MockZohoAPI(candidates_count=2)
    client = ZohoRecruitClient(_test_settings(), transport=httpx.MockTransport(api.handler))
    req = ZohoImportApplicantsRequest(job_id="7001")

    with pytest.raises(HTTPException) as exc_info:
        await import_zoho_applicants(proj_id, req, mock_db, client)

    assert exc_info.value.status_code == 504
    assert "Database commit timed out while importing applicants" in exc_info.value.detail
    assert mock_db.rolled_back is True


# -------------------------------------------------------------------------------------------------
# Test 5: Large document set simulation — efficient batch hash lookup without memory exhaustion
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_large_ats_document_set_duplicate_detection() -> None:
    """Simulates an ATS with 5,000 existing active resumes.

    Only the downloaded batch hashes are looked up, ensuring high performance.
    """
    proj_id = uuid4()
    shared_docs: dict[UUID, DocumentModel] = {}

    # Pre-populate 5,000 mock documents
    for i in range(1, 5001):
        doc_id = uuid4()
        fake_content = f"Mock Resume Content {i}".encode("utf-8")
        f_hash = hashlib.sha256(fake_content).hexdigest()
        shared_docs[doc_id] = DocumentModel(
            id=doc_id,
            project_id=uuid4(),  # other projects
            document_type=DocumentTypeEnum.RESUME,
            original_filename=f"resume_{i}.pdf",
            stored_filename=f"stored_{i}.pdf",
            file_path=f"projects/other/resumes/{i}.pdf",
            file_size_bytes=len(fake_content),
            mime_type="application/pdf",
            file_hash=f_hash,
            processing_stage=ProcessingStageEnum.COMPLETED,
            processing_status=ProcessingStatusEnum.COMPLETED,
            metadata_json={"source": "manual_upload"},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    # Candidate 1 in Zoho will have identical content to document #42 (global duplicate!)
    # Candidate 2 will be brand new
    doc_42_hash = hashlib.sha256(b"Mock Resume Content 42").hexdigest()

    class CustomZohoAPI(MockZohoAPI):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/oauth/v2/token":
                return super().handler(request)
            parts = request.url.path.split("/recruit/v2/")[1].split("/")
            if len(parts) == 4 and parts[0] == "Candidates" and parts[2] == "Attachments":
                att_id = parts[3]
                self.downloads.append(att_id)
                if "cand_1" in att_id:
                    # Content identical to existing ATS document #42!
                    return httpx.Response(
                        200,
                        content=b"Mock Resume Content 42",
                        headers={"Content-Type": "application/pdf"},
                    )
                return httpx.Response(
                    200,
                    content=b"Unique Brand New Content For Candidate 2",
                    headers={"Content-Type": "application/pdf"},
                )
            return super().handler(request)

    api = CustomZohoAPI(candidates_count=2)
    client = ZohoRecruitClient(_test_settings(), transport=httpx.MockTransport(api.handler))
    mock_db = ResilientMockDB(proj_id, shared_docs=shared_docs)
    req = ZohoImportApplicantsRequest(job_id="7001")

    resp = await import_zoho_applicants(proj_id, req, mock_db, client)

    assert resp.candidates_seen == 2
    assert resp.imported_count == 1  # Candidate 2 imported!
    assert resp.already_fetched == 1  # Candidate 1 skipped as duplicate content!
    assert resp.skipped_count == 1
    assert any("duplicate content already imported" in s.get("reason", "") for s in resp.skipped)
    # Total documents grew by exactly 1 (from 5,000 to 5,001)
    assert len(shared_docs) == 5001


# -------------------------------------------------------------------------------------------------
# Test 6: Project isolation — different projects importing different Zoho openings
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_project_isolation_across_different_zoho_job_openings() -> None:
    shared_docs: dict[UUID, DocumentModel] = {}
    api = MockZohoAPI(candidates_count=3)
    client = ZohoRecruitClient(_test_settings(), transport=httpx.MockTransport(api.handler))

    # Project 1 imports Job Opening 7001
    p1 = uuid4()
    db1 = ResilientMockDB(p1, shared_docs=shared_docs)
    req1 = ZohoImportApplicantsRequest(job_id="7001")
    resp1 = await import_zoho_applicants(p1, req1, db1, client)

    assert resp1.imported_count == 3
    assert resp1.new_resumes == 3
    assert len(shared_docs) == 3

    # Project 2 imports Job Opening 7002
    p2 = uuid4()
    db2 = ResilientMockDB(p2, shared_docs=shared_docs)
    req2 = ZohoImportApplicantsRequest(job_id="7002")
    resp2 = await import_zoho_applicants(p2, req2, db2, client)

    assert resp2.imported_count == 3
    assert resp2.new_resumes == 3
    assert len(shared_docs) == 6

    # Verify documents in Project 1 have job 7001 and Project 2 have job 7002
    p1_docs = [d for d in shared_docs.values() if d.project_id == p1]
    p2_docs = [d for d in shared_docs.values() if d.project_id == p2]
    assert len(p1_docs) == 3
    assert len(p2_docs) == 3
    assert all((d.metadata_json or {}).get("zoho_job_opening_id") == "7001" for d in p1_docs)
    assert all((d.metadata_json or {}).get("zoho_job_opening_id") == "7002" for d in p2_docs)


# -------------------------------------------------------------------------------------------------
# Test 7: End-to-end successful import with all fields populated correctly
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_successful_zoho_applicant_import_metadata_and_counts() -> None:
    proj_id = uuid4()
    mock_db = ResilientMockDB(proj_id)
    api = MockZohoAPI(candidates_count=2)
    client = ZohoRecruitClient(_test_settings(), transport=httpx.MockTransport(api.handler))
    req = ZohoImportApplicantsRequest(job_id="7001")

    resp = await import_zoho_applicants(proj_id, req, mock_db, client)

    assert resp.candidates_seen == 2
    assert resp.total_found == 2
    assert resp.imported_count == 2
    assert resp.skipped_count == 0
    assert resp.failed_count == 0
    assert len(resp.document_ids) == 2
    assert mock_db.committed is True

    # Verify document fields
    for doc_id in resp.document_ids:
        doc = mock_db.documents[doc_id]
        assert doc.project_id == proj_id
        assert doc.document_type == DocumentTypeEnum.RESUME
        assert doc.processing_status == ProcessingStatusEnum.UPLOADED
        assert (doc.metadata_json or {}).get("zoho_job_opening_id") == "7001"
        assert (doc.metadata_json or {}).get("zoho_candidate_id") is not None
        assert (doc.metadata_json or {}).get("zoho_attachment_id") is not None
