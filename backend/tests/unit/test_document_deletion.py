from uuid import uuid4

import pytest

from app.db.session import AsyncSessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import DocumentCreate, DocumentType
from app.schemas.project import ProjectCreate
from app.services.document_service import (
    DocumentBelongsToAnotherProjectException,
    DocumentNotFoundException,
    DocumentService,
)
from app.services.project_service import ProjectNotFoundException
from app.services.storage_service import StorageService


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_resume_success() -> None:
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        storage = StorageService()

        project = await projects.create(ProjectCreate(title="Delete Resume Project", target_role="Engineer"))
        marker = uuid4().hex
        doc = await documents.create(
            DocumentCreate(
                project_id=project.id,
                document_type=DocumentType.RESUME,
                original_filename=f"{marker}.txt",
                stored_filename=f"{marker}.txt",
                file_path=f"projects/{project.id}/resumes/{marker}.txt",
                file_size_bytes=100,
                mime_type="text/plain",
                file_hash=marker.ljust(64, "0")[:64],
            )
        )

        service = DocumentService(documents, projects, storage)
        await service.delete_resume(project.id, doc.id)

        # Verify soft-deleted
        retrieved = await documents.get_document(doc.id)
        assert retrieved is None


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_job_description_success() -> None:
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        storage = StorageService()

        project = await projects.create(ProjectCreate(title="Delete JD Project", target_role="Engineer"))
        marker = uuid4().hex
        doc = await documents.create(
            DocumentCreate(
                project_id=project.id,
                document_type=DocumentType.JOB_DESCRIPTION,
                original_filename=f"{marker}.txt",
                stored_filename=f"{marker}.txt",
                file_path=f"projects/{project.id}/job_descriptions/{marker}.txt",
                file_size_bytes=100,
                mime_type="text/plain",
                file_hash=marker.ljust(64, "0")[:64],
            )
        )

        service = DocumentService(documents, projects, storage)
        await service.delete_job_description(project.id)

        # Verify active JD is None
        jd = await documents.get_job_description_by_project(project.id)
        assert jd is None


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_resume_invalid_project() -> None:
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        storage = StorageService()
        service = DocumentService(documents, projects, storage)

        with pytest.raises(ProjectNotFoundException):
            await service.delete_resume(uuid4(), uuid4())


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_resume_invalid_document() -> None:
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        storage = StorageService()

        project = await projects.create(ProjectCreate(title="Invalid Doc Project", target_role="Engineer"))
        service = DocumentService(documents, projects, storage)

        with pytest.raises(DocumentNotFoundException):
            await service.delete_resume(project.id, uuid4())


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_resume_project_mismatch() -> None:
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        storage = StorageService()

        project1 = await projects.create(ProjectCreate(title="Project 1", target_role="Engineer"))
        project2 = await projects.create(ProjectCreate(title="Project 2", target_role="Engineer"))

        marker = uuid4().hex
        doc = await documents.create(
            DocumentCreate(
                project_id=project1.id,
                document_type=DocumentType.RESUME,
                original_filename=f"{marker}.txt",
                stored_filename=f"{marker}.txt",
                file_path=f"projects/{project1.id}/resumes/{marker}.txt",
                file_size_bytes=100,
                mime_type="text/plain",
                file_hash=marker.ljust(64, "0")[:64],
            )
        )

        service = DocumentService(documents, projects, storage)

        with pytest.raises(DocumentBelongsToAnotherProjectException):
            await service.delete_resume(project2.id, doc.id)


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_resume_missing_storage_file_succeeds() -> None:
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        storage = StorageService()

        project = await projects.create(ProjectCreate(title="Missing File Project", target_role="Engineer"))
        marker = uuid4().hex
        doc = await documents.create(
            DocumentCreate(
                project_id=project.id,
                document_type=DocumentType.RESUME,
                original_filename=f"{marker}.txt",
                stored_filename=f"{marker}.txt",
                file_path=f"projects/{project.id}/resumes/non_existent_{marker}.txt",
                file_size_bytes=100,
                mime_type="text/plain",
                file_hash=marker.ljust(64, "0")[:64],
            )
        )

        service = DocumentService(documents, projects, storage)
        await service.delete_resume(project.id, doc.id)
        assert await documents.get_document(doc.id) is None
