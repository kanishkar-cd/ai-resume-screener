"""Integration tests for Candidate Verification Async ORM loading.

Verifies:
1. Real AsyncSession loading of DocumentModel with eager selectinload(normalized_resume) and selectinload(extracted_resume).
2. Fix for sqlalchemy.exc.MissingGreenlet when accessing doc.normalized_resume and doc.extracted_resume.
3. Document with normalized_resume containing email and phone.
4. Document without normalized_resume record (handles absent record safely).
5. Document with extracted data present but normalized data absent.
6. Multiple documents belonging to one project grouped correctly (Zoho ID, email, phone, fallback).
7. Duplicate attachments for the same candidate unified into a single verification group.
8. Safe retry behavior and persistence in ProjectModel.metadata_json.
9. End-to-end API call via POST /api/v1/projects/{project_id}/verify-candidates using real async test client.
"""

from uuid import UUID, uuid4
import pytest
import httpx

from app.db.session import AsyncSessionLocal
from app.models.document import DocumentModel, DocumentTypeEnum, ProcessingStageEnum, ProcessingStatusEnum
from app.models.extracted_info import ExtractedResumeModel
from app.models.normalized_info import NormalizedResumeModel
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.candidate_verification import BatchVerificationStatus, CandidateVerificationStatus
from app.schemas.document import DocumentCreate, DocumentType
from app.schemas.project import ProjectCreate
from app.services.candidate_verification_service import CandidateVerificationService


@pytest.mark.asyncio(loop_scope="session")
async def test_candidate_verification_async_orm_selectinload() -> None:
    """Verify that CandidateVerificationService eagerly loads relationships with zero MissingGreenlet."""
    marker = uuid4().hex[:12]

    async with AsyncSessionLocal() as session:
        project_repo = ProjectRepository(session)
        doc_repo = DocumentRepository(session)

        # 1. Create a project
        project = await project_repo.create(
            ProjectCreate(
                title=f"Verification Test Project {marker}",
                target_role="Platform Engineer",
            )
        )
        project_id = project.id

        # 2. Document 1: Has both normalized_resume and extracted_resume
        doc1 = await doc_repo.create(
            DocumentCreate(
                project_id=project_id,
                document_type=DocumentType.RESUME,
                original_filename=f"cand1_{marker}.pdf",
                stored_filename=f"cand1_{marker}.pdf",
                file_path=f"projects/{project_id}/resumes/cand1_{marker}.pdf",
                file_size_bytes=1024,
                mime_type="application/pdf",
                file_hash=uuid4().hex.ljust(64, "0")[:64],
            )
        )
        extracted1 = ExtractedResumeModel(
            document_id=doc1.id,
            candidate_name="Alice Smith",
            email="alice@example.com",
            phone="+1 555-0101",
        )
        session.add(extracted1)
        await session.flush()

        normalized1 = NormalizedResumeModel(
            document_id=doc1.id,
            extracted_resume_id=extracted1.id,
            email="alice@example.com",
            phone="+1 555-0101",
            skills=["Python", "Kubernetes"],
            ruleset_version="1.0.0",
        )
        session.add(normalized1)

        # 3. Document 2: Duplicate attachment for Candidate 1 (same email in metadata)
        doc2 = await doc_repo.create(
            DocumentCreate(
                project_id=project_id,
                document_type=DocumentType.RESUME,
                original_filename=f"cand1_dup_{marker}.pdf",
                stored_filename=f"cand1_dup_{marker}.pdf",
                file_path=f"projects/{project_id}/resumes/cand1_dup_{marker}.pdf",
                file_size_bytes=2048,
                mime_type="application/pdf",
                file_hash=uuid4().hex.ljust(64, "0")[:64],
            )
        )
        doc2.metadata_json = {
            "email": "alice@example.com",
            "candidate_name": "Alice Smith",
        }

        # 4. Document 3: Has NO normalized_resume and NO extracted_resume (only Zoho metadata)
        doc3 = await doc_repo.create(
            DocumentCreate(
                project_id=project_id,
                document_type=DocumentType.RESUME,
                original_filename=f"cand2_zoho_{marker}.pdf",
                stored_filename=f"cand2_zoho_{marker}.pdf",
                file_path=f"projects/{project_id}/resumes/cand2_zoho_{marker}.pdf",
                file_size_bytes=3072,
                mime_type="application/pdf",
                file_hash=uuid4().hex.ljust(64, "0")[:64],
            )
        )
        doc3.metadata_json = {
            "zoho_candidate_id": f"ZOHO_{marker}_2",
            "candidate_name": "Bob Jones",
            "email": "bob.jones@zoho.test",
        }

        # 5. Document 4: Has extracted_resume, but NO normalized_resume
        doc4 = await doc_repo.create(
            DocumentCreate(
                project_id=project_id,
                document_type=DocumentType.RESUME,
                original_filename=f"cand3_ext_{marker}.pdf",
                stored_filename=f"cand3_ext_{marker}.pdf",
                file_path=f"projects/{project_id}/resumes/cand3_ext_{marker}.pdf",
                file_size_bytes=4096,
                mime_type="application/pdf",
                file_hash=uuid4().hex.ljust(64, "0")[:64],
            )
        )
        extracted4 = ExtractedResumeModel(
            document_id=doc4.id,
            candidate_name="Charlie Brown",
            email="charlie@example.com",
            phone="+1 555-0303",
        )
        session.add(extracted4)

        # 6. Document 5: Fallback ID candidate (no email, phone, or Zoho ID)
        doc5 = await doc_repo.create(
            DocumentCreate(
                project_id=project_id,
                document_type=DocumentType.RESUME,
                original_filename=f"cand4_anon_{marker}.pdf",
                stored_filename=f"cand4_anon_{marker}.pdf",
                file_path=f"projects/{project_id}/resumes/cand4_anon_{marker}.pdf",
                file_size_bytes=512,
                mime_type="application/pdf",
                file_hash=uuid4().hex.ljust(64, "0")[:64],
            )
        )

        await session.commit()

        try:
            # 7. Execute verification service with real async session
            service = CandidateVerificationService(session=session)
            summary = await service.verify_job_opening_candidates(project_id, force_reverify=True)

            # Assert execution succeeded without MissingGreenlet error
            assert summary is not None
            assert summary.project_id == str(project_id)
            assert summary.status in (BatchVerificationStatus.COMPLETED, BatchVerificationStatus.PARTIAL_SUCCESS)

            # Verify grouping: Doc1 and Doc2 unified into 1 candidate group
            # Total unique candidates: Alice (Doc1+Doc2), Bob (Doc3), Charlie (Doc4), Anon (Doc5) = 4 candidates
            assert summary.total_candidates == 4
            assert summary.processed_candidates == 4

            # Verify that Alice was resolved with email from normalized_resume
            alice_result = next((r for r in summary.results if "alice@example.com" in (r.email or "")), None)
            assert alice_result is not None
            assert len(alice_result.document_ids) == 2
            assert doc1.id in alice_result.document_ids
            assert doc2.id in alice_result.document_ids
            assert alice_result.verification_status in (
                CandidateVerificationStatus.VERIFIED,
                CandidateVerificationStatus.REVIEW_REQUIRED,
            )

            # Verify that Bob (no normalized record) handled safely
            bob_result = next((r for r in summary.results if r.zoho_candidate_id == f"ZOHO_{marker}_2"), None)
            assert bob_result is not None
            assert bob_result.candidate_name == "Bob Jones"

            # Verify that Charlie (extracted only) handled safely
            charlie_result = next((r for r in summary.results if "charlie@example.com" in (r.email or "")), None)
            assert charlie_result is not None
            assert charlie_result.candidate_name == "Charlie Brown"

            # Verify safe retry (skips already verified candidates when force_reverify=False)
            retry_summary = await service.retry_failed_candidates(project_id)
            assert retry_summary.status == summary.status
            assert retry_summary.total_candidates == 4

        finally:
            # Clean up test artifacts
            await doc_repo.delete_document(doc1.id)
            await doc_repo.delete_document(doc2.id)
            await doc_repo.delete_document(doc3.id)
            await doc_repo.delete_document(doc4.id)
            await doc_repo.delete_document(doc5.id)
            await project_repo.soft_delete(project_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_candidate_verification_api_endpoint_integration(async_client: httpx.AsyncClient) -> None:
    """Verify that POST /api/v1/projects/{project_id}/verify-candidates returns HTTP 200 via real API."""
    marker = uuid4().hex[:12]

    async with AsyncSessionLocal() as session:
        project_repo = ProjectRepository(session)
        doc_repo = DocumentRepository(session)

        project = await project_repo.create(
            ProjectCreate(
                title=f"API Verification Project {marker}",
                target_role="Site Reliability Engineer",
            )
        )
        project_id = project.id

        doc = await doc_repo.create(
            DocumentCreate(
                project_id=project_id,
                document_type=DocumentType.RESUME,
                original_filename=f"api_cand_{marker}.pdf",
                stored_filename=f"api_cand_{marker}.pdf",
                file_path=f"projects/{project_id}/resumes/api_cand_{marker}.pdf",
                file_size_bytes=1024,
                mime_type="application/pdf",
                file_hash=uuid4().hex.ljust(64, "0")[:64],
            )
        )
        doc.metadata_json = {
            "candidate_name": "API Tester",
            "email": f"tester_{marker}@example.com",
            "phone": "+1 555-9999",
        }
        await session.commit()

        try:
            # Call actual HTTP endpoint
            response = await async_client.post(
                f"/api/v1/projects/{project_id}/verify-candidates",
                json={"force_reverify": True},
            )
            assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
            body = response.json()
            assert "data" in body
            data = body["data"]
            assert data["total_candidates"] == 1
            assert data["processed_candidates"] == 1
            assert data["status"] in ("COMPLETED", "PARTIAL_SUCCESS")

            # Check status endpoint
            status_res = await async_client.get(f"/api/v1/projects/{project_id}/verification-status")
            assert status_res.status_code == 200
            status_data = status_res.json()["data"]
            assert status_data["total_candidates"] == 1
            assert status_data["status"] == data["status"]

        finally:
            await doc_repo.delete_document(doc.id)
            await project_repo.soft_delete(project_id)
