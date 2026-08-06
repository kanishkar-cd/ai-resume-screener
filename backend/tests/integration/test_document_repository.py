from io import BytesIO
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.db.session import AsyncSessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import DocumentType, ProcessingStatus, SortOrder
from app.schemas.project import ProjectCreate
from app.services.document_service import DocumentService, DuplicateDocumentException
from app.services.storage_service import StorageService


def text_upload(content: bytes) -> UploadFile:
    return UploadFile(
        BytesIO(content),
        filename="candidate.txt",
        headers=Headers({"content-type": "text/plain"}),
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_upload_stores_project_metadata_file_and_detects_duplicate(
    tmp_path,
) -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        project_repository = ProjectRepository(session)
        project = await project_repository.create(
            ProjectCreate(title=f"Documents {marker}", target_role="Engineer")
        )
        document_repository = DocumentRepository(session)
        storage = StorageService(tmp_path / "projects")
        service = DocumentService(document_repository, project_repository, storage)
        content = f"candidate {marker}".encode()

        uploaded = await service.upload_document(
            project.id, DocumentType.RESUME, text_upload(content)
        )
        record = await document_repository.get_by_id(uploaded.document_id)

        assert record is not None
        assert record.project_id == project.id
        assert record.processing_status.value == "UPLOADED"
        assert record.file_hash
        assert record.file_size_bytes == len(content)
        assert storage.get_file_path(
            record.stored_filename, project.id, "resumes"
        ).read_bytes() == content

        listed = await service.list_documents(
            project.id,
            DocumentType.RESUME,
            ProcessingStatus.UPLOADED,
            "candidate",
            1,
            10,
            SortOrder.DESC,
        )
        assert listed.total == 1
        assert listed.items[0].id == record.id

        download = await service.download_document(record.id)
        assert download.path.read_bytes() == content
        assert download.filename == "candidate.txt"

        with pytest.raises(DuplicateDocumentException):
            await service.upload_document(
                project.id, DocumentType.RESUME, text_upload(content)
            )

        await service.delete_document(record.id)
        assert await document_repository.get_document(record.id) is None
        assert not download.path.exists()
        assert await project_repository.soft_delete(project.id) is True
