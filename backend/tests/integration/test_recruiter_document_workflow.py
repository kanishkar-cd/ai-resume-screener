from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.db.session import AsyncSessionLocal
from app.models.document import DocumentModel
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import SortOrder
from app.schemas.project import ProjectCreate
from app.services.document_service import DocumentService
from app.services.storage_service import StorageService


def text_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(
        BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": "text/plain"}),
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_job_replacement_partial_batch_and_resume_listing(tmp_path: Path) -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        storage = StorageService(tmp_path / "projects")
        service = DocumentService(documents, projects, storage)
        project = await projects.create(
            ProjectCreate(title=f"Workflow {marker}", target_role="Engineer")
        )

        first = await service.upload_job_description(
            project.id, text_upload("job-one.txt", f"first {marker}".encode())
        )
        second = await service.upload_job_description(
            project.id, text_upload("job-two.txt", f"second {marker}".encode())
        )
        active_job = await documents.get_job_description_by_project(project.id)
        first_record = await session.get(DocumentModel, first.document_id)
        assert active_job is not None and active_job.id == second.document_id
        assert first_record is not None and first_record.deleted_at is not None
        assert "job_description" in active_job.file_path

        batch = await service.upload_resume_batch(
            project.id,
            [
                text_upload("alice.txt", f"Alice {marker}".encode()),
                UploadFile(
                    BytesIO(b"bad"),
                    filename="virus.exe",
                    headers=Headers({"content-type": "application/octet-stream"}),
                ),
            ],
        )
        assert batch.total_received == 2
        assert batch.successful_count == 1
        assert batch.failed_count == 1
        assert batch.failed_uploads[0].error_code == "INVALID_FILE_TYPE"

        resumes = await service.list_project_resumes(
            project.id, None, "alice", 1, 20, SortOrder.DESC
        )
        assert resumes.total == 1
        assert resumes.items[0].document_type.value == "RESUME"

        resume_record = await documents.get_document(
            batch.successful_uploads[0].document_id
        )
        assert resume_record is not None
        await service.delete_document(resume_record.id)
        await service.delete_document(active_job.id)
        await projects.soft_delete(project.id)
