from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.schemas.document import ProcessingStage, ProcessingStatus
from app.schemas.parsed_document import ParserEngineEnum
from app.services.document_service import DocumentNotFoundException
from app.services.parsers.base_parser import (
    DocumentParsingException,
    ExtractionResult,
    UnsupportedFormatException,
)
from app.services.parsing_service import ParserFactory, ParsingService


def parsing_fixture(mime_type: str = "text/plain"):
    document = SimpleNamespace(
        id=uuid4(), mime_type=mime_type, file_path="resume.txt"
    )
    documents = AsyncMock()
    documents.get_document.return_value = document
    parsed = AsyncMock()
    parsed.get_by_document_id.return_value = None
    storage = Mock()
    storage.resolve_file.return_value = Path("resume.txt")
    return ParsingService(documents, parsed, storage), documents, parsed, document


@pytest.mark.asyncio
async def test_missing_document_is_rejected() -> None:
    service, documents, _, document = parsing_fixture()
    documents.get_document.return_value = None
    with pytest.raises(DocumentNotFoundException):
        await service.parse_document(document.id)


@pytest.mark.asyncio
async def test_duplicate_parsing_is_idempotent() -> None:
    service, _, parsed, document = parsing_fixture()
    parsed.get_by_document_id.return_value = SimpleNamespace(id=uuid4())
    response = await service.parse_document(document.id)
    assert response.status == ProcessingStatus.COMPLETED
    parsed.create_or_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_format_marks_document_failed() -> None:
    service, documents, _, document = parsing_fixture("application/octet-stream")
    with pytest.raises(UnsupportedFormatException):
        await service.parse_document(document.id)
    failed_call = documents.update_processing.await_args
    assert failed_call.args[1:3] == (
        ProcessingStage.FAILED,
        ProcessingStatus.FAILED,
    )


@pytest.mark.asyncio
async def test_parser_exception_is_translated_and_marks_failed() -> None:
    service, documents, _, document = parsing_fixture()
    parser = Mock()
    parser.parse.side_effect = RuntimeError("parser exploded")
    with patch.object(ParserFactory, "create", return_value=parser):
        with pytest.raises(DocumentParsingException):
            await service.parse_document(document.id)
    assert documents.update_processing.await_args.args[1] == ProcessingStage.FAILED


@pytest.mark.asyncio
async def test_successful_parse_persists_normalized_text_and_completes() -> None:
    service, documents, parsed, document = parsing_fixture()
    parser = Mock()
    parser.parse.return_value = ExtractionResult(
        "Python   Engineer", 1, ParserEngineEnum.PLAIN_TEXT, {}
    )
    parsed.create_or_update.return_value = SimpleNamespace(id=uuid4())
    with patch.object(ParserFactory, "create", return_value=parser):
        response = await service.parse_document(document.id)
    payload = parsed.create_or_update.await_args.args[0]
    assert payload.normalized_text == "Python Engineer"
    assert response.processing_stage == ProcessingStage.COMPLETED
    assert documents.update_processing.await_args.args[1:3] == (
        ProcessingStage.COMPLETED,
        ProcessingStatus.COMPLETED,
    )
