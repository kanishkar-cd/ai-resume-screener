from io import BytesIO
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.db.session import AsyncSessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import DocumentType
from app.schemas.parsed_document import ParsedDocumentCreate, ParserEngineEnum
from app.schemas.project import ProjectCreate
from app.services.document_service import DocumentService
from app.services.parsing_service import ParsingService
from app.services.storage_service import StorageService


@pytest.mark.asyncio(loop_scope="session")
async def test_parsed_document_upsert_and_txt_pipeline(tmp_path) -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        documents = DocumentRepository(session)
        parsed_documents = ParsedDocumentRepository(session)
        storage = StorageService(tmp_path / "projects")
        project = await projects.create(
            ProjectCreate(title=f"Parsing {marker}", target_role="Engineer")
        )
        upload_service = DocumentService(documents, projects, storage)
        upload = UploadFile(
            BytesIO(f"Senior   Python Engineer {marker}".encode()),
            filename="resume.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        uploaded = await upload_service.upload_document(
            project.id, DocumentType.RESUME, upload
        )

        parsing_service = ParsingService(documents, parsed_documents, storage)
        response = await parsing_service.parse_document(uploaded.document_id)
        parsed = await parsed_documents.get_by_document_id(uploaded.document_id)
        parent = await documents.get_document(uploaded.document_id)

        assert response.processing_status.value == "PARSED"
        assert parsed is not None
        assert "Python Engineer" in parsed.normalized_text
        assert parsed.parser_engine == "PLAIN_TEXT"
        assert parsed.word_count >= 4
        assert parent is not None
        assert parent.processing_status.value == "PARSED"
        assert parent.error_message is None

        original_id = parsed.id
        updated = await parsed_documents.upsert(
            ParsedDocumentCreate(
                document_id=uploaded.document_id,
                raw_text="updated",
                normalized_text="updated",
                page_count=1,
                word_count=1,
                character_count=7,
                parser_engine=ParserEngineEnum.PLAIN_TEXT,
                parsing_duration_ms=1.0,
            )
        )
        assert updated.id == original_id
        assert await parsed_documents.delete_by_document_id(uploaded.document_id)

        await upload_service.delete_document(uploaded.document_id)
        await projects.soft_delete(project.id)
