from io import BytesIO
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.db.session import AsyncSessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import DocumentType
from app.schemas.project import ProjectCreate
from app.services.document_service import DocumentService
from app.services.extraction_service import ExtractionService
from app.services.parsing_service import ParsingService
from app.services.storage_service import StorageService


@pytest.mark.asyncio(loop_scope="session")
async def test_stage3_resume_extraction_upserts_and_persists(tmp_path) -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        parsed = ParsedDocumentRepository(session)
        extracted = ExtractionRepository(session)
        storage = StorageService(tmp_path / "projects")
        project = await projects.create(ProjectCreate(title=f"Extract {marker}", target_role="Engineer"))
        document_service = DocumentService(documents, projects, storage)
        upload = UploadFile(
            BytesIO(f"Jane Doe\njane@example.com\nSKILLS\nPython FastAPI PostgreSQL\n{marker}".encode()),
            filename="resume.txt", headers=Headers({"content-type": "text/plain"}),
        )
        uploaded = await document_service.upload_document(project.id, DocumentType.RESUME, upload)
        await ParsingService(documents, parsed, storage).parse_document(uploaded.document_id)
        service = ExtractionService(documents, parsed, extracted)
        await service.extract_document_data(uploaded.document_id)
        first = await extracted.get_resume_by_document_id(uploaded.document_id)
        await service.extract_document_data(uploaded.document_id)
        second = await extracted.get_resume_by_document_id(uploaded.document_id)
        parent = await documents.get_document(uploaded.document_id)
        assert first is not None and second is not None and first.id == second.id
        assert first.email == "jane@example.com" and "Python" in first.skills
        assert first.confidence_scores["email"] == 0.98
        assert parent.processing_stage.value == "COMPLETED"
        await document_service.delete_document(uploaded.document_id)
        await projects.soft_delete(project.id)
