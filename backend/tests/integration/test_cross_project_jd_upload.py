from io import BytesIO
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.db.session import AsyncSessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import DocumentType
from app.schemas.project import ProjectCreate
from app.services.document_service import DocumentService, DuplicateDocumentException
from app.services.storage_service import StorageService


@pytest.mark.asyncio(loop_scope="session")
async def test_cross_project_and_same_project_jd_upload_rules(tmp_path) -> None:
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        storage = StorageService(tmp_path / "projects")
        upload_service = DocumentService(documents, projects, storage)

        # Create two distinct projects
        p1 = await projects.create(ProjectCreate(title=f"Project 1 {uuid4().hex}", target_role="Backend Developer"))
        p2 = await projects.create(ProjectCreate(title=f"Project 2 {uuid4().hex}", target_role="Frontend Developer"))

        sample_jd_content = b"Senior Python Backend Engineer JD content for duplicate scope testing."

        # TEST 1: Upload JD A to Project 1 -> SUCCESS
        file_p1_jd1 = UploadFile(
            BytesIO(sample_jd_content),
            filename="Software_Engineer_JD.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        res_p1_jd1 = await upload_service.upload_job_description(p1.id, file_p1_jd1)
        assert res_p1_jd1.project_id == p1.id
        assert res_p1_jd1.filename == "Software_Engineer_JD.txt"

        # TEST 2: Upload exact same JD A to Project 2 -> SUCCESS
        file_p2_jd1 = UploadFile(
            BytesIO(sample_jd_content),
            filename="Software_Engineer_JD.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        res_p2_jd1 = await upload_service.upload_job_description(p2.id, file_p2_jd1)
        assert res_p2_jd1.project_id == p2.id
        assert res_p2_jd1.filename == "Software_Engineer_JD.txt"

        # TEST 3: Upload exact same JD A again to Project 1 -> DUPLICATE ERROR
        file_p1_jd1_dup = UploadFile(
            BytesIO(sample_jd_content),
            filename="Software_Engineer_JD.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        with pytest.raises(DuplicateDocumentException):
            await upload_service.upload_job_description(p1.id, file_p1_jd1_dup)

        # TEST 4: Upload a different JD B to Project 1 -> SUCCESS (replaces prior active JD)
        different_jd_content = b"Principal Cloud Architect JD content for replacement test."
        file_p1_jd2 = UploadFile(
            BytesIO(different_jd_content),
            filename="Architect_JD.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        res_p1_jd2 = await upload_service.upload_job_description(p1.id, file_p1_jd2)
        assert res_p1_jd2.project_id == p1.id
        assert res_p1_jd2.filename == "Architect_JD.txt"

        # TEST 5: Resume files follow project-scoped duplicate rules
        sample_resume_content = b"Candidate Resume content for duplicate scope testing."
        file_p1_res1 = UploadFile(
            BytesIO(sample_resume_content),
            filename="John_Doe_Resume.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        res_p1_res1 = await upload_service.upload_document(p1.id, DocumentType.RESUME, file_p1_res1)
        assert res_p1_res1.project_id == p1.id

        file_p2_res1 = UploadFile(
            BytesIO(sample_resume_content),
            filename="John_Doe_Resume.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        res_p2_res1 = await upload_service.upload_document(p2.id, DocumentType.RESUME, file_p2_res1)
        assert res_p2_res1.project_id == p2.id

        file_p1_res1_dup = UploadFile(
            BytesIO(sample_resume_content),
            filename="John_Doe_Resume.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        with pytest.raises(DuplicateDocumentException):
            await upload_service.upload_document(p1.id, DocumentType.RESUME, file_p1_res1_dup)

        # TEST 6: Different document types with exact same content/hash in Project 1 do not conflict
        dual_type_content = b"Identical byte sequence for resume and job description in same project."
        file_p1_dual_jd = UploadFile(
            BytesIO(dual_type_content),
            filename="dual_doc.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        await upload_service.upload_job_description(p1.id, file_p1_dual_jd)

        file_p1_dual_resume = UploadFile(
            BytesIO(dual_type_content),
            filename="dual_doc.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        dual_res = await upload_service.upload_document(p1.id, DocumentType.RESUME, file_p1_dual_resume)
        assert dual_res.project_id == p1.id

        # Verify DB records for Project 1 and Project 2
        p1_active_jd = await documents.get_job_description_by_project(p1.id)
        p2_active_jd = await documents.get_job_description_by_project(p2.id)
        assert p1_active_jd is not None and p2_active_jd is not None
        assert p1_active_jd.project_id == p1.id
        assert p2_active_jd.project_id == p2.id

        # Clean up
        await projects.soft_delete(p1.id)
        await projects.soft_delete(p2.id)
