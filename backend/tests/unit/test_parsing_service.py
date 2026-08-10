from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.models.document import (
    DocumentTypeEnum,
    ProcessingStageEnum,
    ProcessingStatusEnum,
)
from app.schemas.document import ProcessingStatus
from app.schemas.parsed_document import ParserEngine
from app.services.document_service import (
    DocumentFileMissingException,
    DocumentNotFoundException,
)
from app.services.parsers.base import text_metrics
from app.services.parsers.txt_parser import parse_txt
from app.services.parsing_service import (
    DocumentNotParseableException,
    DocumentParseFailedException,
    ParsedDocumentNotFoundException,
    ParsingService,
)


def document_record(
    *,
    status: ProcessingStatusEnum = ProcessingStatusEnum.UPLOADED,
    mime_type: str = "text/plain",
    file_path: str = "stored/resume.txt",
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        document_type=DocumentTypeEnum.RESUME,
        original_filename="resume.txt",
        stored_filename=f"{uuid4()}.txt",
        file_path=file_path,
        file_size_bytes=12,
        mime_type=mime_type,
        file_hash="a" * 64,
        processing_stage=ProcessingStageEnum.UPLOAD,
        processing_status=status,
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


def service_fixture() -> tuple[ParsingService, AsyncMock, AsyncMock, Mock]:
    documents = AsyncMock()
    documents.session = AsyncMock()
    parsed = AsyncMock()
    storage = Mock()
    return ParsingService(documents, parsed, storage), documents, parsed, storage


def test_text_metrics_counts_words_and_characters() -> None:
    assert text_metrics("hello world") == (2, 11)


def test_parse_txt_returns_plain_text_engine(tmp_path: Path) -> None:
    path = tmp_path / "resume.txt"
    path.write_text("Senior engineer\nFastAPI", encoding="utf-8")
    result = parse_txt(path)
    assert result.parser_engine == ParserEngine.PLAIN_TEXT
    assert result.page_count == 1
    assert "FastAPI" in result.raw_text


@pytest.mark.asyncio
async def test_parse_rejects_missing_document() -> None:
    service, documents, _, _ = service_fixture()
    documents.get_document.return_value = None
    with pytest.raises(DocumentNotFoundException):
        await service.parse_document(uuid4())


@pytest.mark.asyncio
async def test_parse_rejects_parsing_pending_status() -> None:
    service, documents, _, _ = service_fixture()
    documents.get_document.return_value = document_record(
        status=ProcessingStatusEnum.PARSING_PENDING
    )
    with pytest.raises(DocumentNotParseableException):
        await service.parse_document(uuid4())


@pytest.mark.asyncio
async def test_parse_rejects_missing_file() -> None:
    service, documents, _, storage = service_fixture()
    documents.get_document.return_value = document_record()
    storage.resolve_file.return_value = None
    with pytest.raises(DocumentFileMissingException):
        await service.parse_document(uuid4())


@pytest.mark.asyncio
async def test_parse_txt_success_persists_and_sets_parsed(
    tmp_path: Path,
) -> None:
    service, documents, parsed, storage = service_fixture()
    record = document_record(file_path=str(tmp_path / "resume.txt"))
    path = tmp_path / "resume.txt"
    path.write_text("Alice Python FastAPI", encoding="utf-8")
    documents.get_document.return_value = record
    storage.resolve_file.return_value = path

    pending = document_record(status=ProcessingStatusEnum.PARSING_PENDING)
    pending.id = record.id
    success = document_record(status=ProcessingStatusEnum.PARSED)
    success.id = record.id
    documents.update_status.side_effect = [pending, success]
    parsed.upsert.return_value = SimpleNamespace(id=uuid4())

    result = await service.parse_document(record.id)

    assert result.processing_status == ProcessingStatus.PARSED
    assert result.message == "Document parsed successfully."
    assert documents.update_status.await_count == 2
    assert documents.update_status.await_args_list[0].args[1] == ProcessingStatus.PARSING_PENDING
    assert documents.update_status.await_args_list[1].args[1] == ProcessingStatus.PARSED
    payload = parsed.upsert.await_args.args[0]
    assert payload.parser_engine == ParserEngine.PLAIN_TEXT
    assert payload.word_count == 3
    assert "Alice" in payload.raw_text
    documents.session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_parse_marks_failed_on_parser_error(tmp_path: Path) -> None:
    service, documents, _, storage = service_fixture()
    record = document_record(
        mime_type="application/pdf",
        file_path=str(tmp_path / "broken.pdf"),
    )
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not-a-pdf")
    documents.get_document.return_value = record
    storage.resolve_file.return_value = path
    documents.update_status.side_effect = [
        document_record(status=ProcessingStatusEnum.PARSING_PENDING),
        document_record(status=ProcessingStatusEnum.FAILED),
    ]

    with pytest.raises(DocumentParseFailedException):
        await service.parse_document(record.id)

    assert documents.update_status.await_args_list[-1].args[1] == ProcessingStatus.FAILED


@pytest.mark.asyncio
async def test_get_parsed_document_not_found() -> None:
    service, documents, parsed, _ = service_fixture()
    documents.get_document.return_value = document_record()
    parsed.get_by_document_id.return_value = None
    with pytest.raises(ParsedDocumentNotFoundException):
        await service.get_parsed_document(uuid4())
