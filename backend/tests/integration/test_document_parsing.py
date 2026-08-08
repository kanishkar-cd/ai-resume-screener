from io import BytesIO
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.db.session import AsyncSessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import DocumentType, ProcessingStatus
from app.schemas.project import ProjectCreate
from app.services.document_service import DocumentService
from app.services.parsing_service import ParsingService
from app.services.storage_service import StorageService


def text_upload(content: bytes, filename: str = "candidate.txt") -> UploadFile:
    return UploadFile(
        BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": "text/plain"}),
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_parse_persists_text_and_updates_status(tmp_path) -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        project_repository = ProjectRepository(session)
        project = await project_repository.create(
            ProjectCreate(title=f"Parse {marker}", target_role="Engineer")
        )
        document_repository = DocumentRepository(session)
        parsed_repository = ParsedDocumentRepository(session)
        storage = StorageService(tmp_path / "projects")
        documents = DocumentService(
            document_repository, project_repository, storage
        )
        parsing = ParsingService(
            document_repository, parsed_repository, storage
        )

        content = f"Alice Python FastAPI {marker}".encode()
        uploaded = await documents.upload_document(
            project.id, DocumentType.RESUME, text_upload(content)
        )

        result = await parsing.parse_document(uploaded.document_id)
        assert result.processing_status == ProcessingStatus.PARSED

        record = await document_repository.get_document(uploaded.document_id)
        assert record is not None
        assert record.processing_status.value == "PARSED"

        parsed = await parsing.get_parsed_document(uploaded.document_id)
        assert parsed.parser_engine.value == "PLAIN_TEXT"
        assert marker in parsed.raw_text
        assert parsed.word_count >= 3
        assert parsed.character_count == len(content)
        assert parsed.page_count == 1

        await documents.delete_document(uploaded.document_id)
        assert await project_repository.soft_delete(project.id) is True
