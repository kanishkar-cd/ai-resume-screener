from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from app.api.v1.endpoints.parsing import get_parsing_service
from app.main import app
from app.schemas.document import ProcessingStage, ProcessingStatus
from app.schemas.parsed_document import (
    DocumentParseRead,
    ParsedDocumentRead,
    ParserEngine,
)
from app.services.document_service import DocumentNotFoundException
from app.services.parsing_service import ParsedDocumentNotFoundException


class FakeParsingService:
    def __init__(self) -> None:
        self.document_id = uuid4()
        now = datetime.now(UTC)
        self.parsed = ParsedDocumentRead(
            id=uuid4(),
            document_id=self.document_id,
            raw_text="Senior Python engineer",
            page_count=1,
            word_count=3,
            character_count=22,
            parser_engine=ParserEngine.PLAIN_TEXT,
            parsing_duration_ms=4.2,
            created_at=now,
            updated_at=now,
        )

    async def parse_document(self, document_id):
        if document_id != self.document_id:
            raise DocumentNotFoundException()
        return DocumentParseRead(
            document_id=document_id,
            processing_status=ProcessingStatus.PARSED,
            processing_stage=ProcessingStage.UPLOAD,
            message="Document parsed successfully.",
        )

    async def get_parsed_document(self, document_id):
        if document_id != self.document_id:
            raise ParsedDocumentNotFoundException()
        return self.parsed


@pytest.mark.asyncio
async def test_parse_and_get_parsed_contracts(
    async_client: httpx.AsyncClient,
) -> None:
    service = FakeParsingService()
    app.dependency_overrides[get_parsing_service] = lambda: service

    unknown = await async_client.get(f"/api/v1/documents/{uuid4()}/parsed")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "PARSED_DOCUMENT_NOT_FOUND"

    response = await async_client.post(
        f"/api/v1/documents/{service.document_id}/parse"
    )
    assert response.status_code == 200
    assert response.json()["data"] == {
        "document_id": str(service.document_id),
        "processing_status": "PARSED",
        "processing_stage": "UPLOAD",
        "message": "Document parsed successfully.",
    }

    fetched = await async_client.get(
        f"/api/v1/documents/{service.document_id}/parsed"
    )
    assert fetched.status_code == 200
    body = fetched.json()["data"]
    assert body["document_id"] == str(service.document_id)
    assert body["raw_text"] == "Senior Python engineer"
    assert body["parser_engine"] == "PLAIN_TEXT"
    assert body["word_count"] == 3
