from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.parsing import get_parsing_service
from app.main import app
from app.schemas.document import ProcessingStage, ProcessingStatus
from app.schemas.parsed_document import (
    ParsedDocumentRead,
    ParserEngineEnum,
    ParseDocumentResponse,
)
from app.services.parsing_service import ParsedDocumentNotFoundException


class FakeParsingService:
    def __init__(self) -> None:
        self.document_id = uuid4()
        now = datetime.now(UTC)
        self.parsed = ParsedDocumentRead(
            id=uuid4(),
            document_id=self.document_id,
            normalized_text="Senior Python Engineer",
            page_count=1,
            word_count=3,
            character_count=22,
            language="en",
            parser_engine=ParserEngineEnum.PLAIN_TEXT,
            parsing_duration_ms=2.5,
            parsing_metadata={"encoding": "utf-8"},
            created_at=now,
            updated_at=now,
        )

    async def prepare_parsing(
        self, document_id: UUID
    ) -> tuple[ParseDocumentResponse, bool]:
        return (
            ParseDocumentResponse(
                document_id=document_id,
                status=ProcessingStatus.COMPLETED,
                processing_stage=ProcessingStage.COMPLETED,
                message="Document was already parsed.",
            ),
            False,
        )

    async def get_parsed_document(self, document_id: UUID) -> ParsedDocumentRead:
        if document_id != self.document_id:
            raise ParsedDocumentNotFoundException()
        return self.parsed


class FakeQueuedParsingService(FakeParsingService):
    async def prepare_parsing(
        self, document_id: UUID
    ) -> tuple[ParseDocumentResponse, bool]:
        return (
            ParseDocumentResponse(
                document_id=document_id,
                status=ProcessingStatus.IN_PROGRESS,
                processing_stage=ProcessingStage.PARSING,
                message="Document parsing accepted.",
            ),
            True,
        )


@pytest.mark.asyncio
async def test_parse_and_get_parsed_document_api(
    async_client: httpx.AsyncClient,
) -> None:
    service = FakeParsingService()
    app.dependency_overrides[get_parsing_service] = lambda: service

    triggered = await async_client.post(
        f"/api/v1/documents/{service.document_id}/parse"
    )
    assert triggered.status_code == 202
    assert triggered.json()["data"]["status"] == "COMPLETED"

    fetched = await async_client.get(
        f"/api/v1/documents/{service.document_id}/parsed"
    )
    assert fetched.status_code == 200
    assert fetched.json()["data"]["normalized_text"] == "Senior Python Engineer"
    assert fetched.json()["data"]["parser_engine"] == "PLAIN_TEXT"

    missing = await async_client.get(f"/api/v1/documents/{uuid4()}/parsed")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PARSED_DOCUMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_parse_endpoint_schedules_background_task(
    async_client: httpx.AsyncClient,
) -> None:
    service = FakeQueuedParsingService()
    app.dependency_overrides[get_parsing_service] = lambda: service
    worker = AsyncMock()
    with patch("app.api.v1.endpoints.parsing.run_parsing_task", worker):
        response = await async_client.post(
            f"/api/v1/documents/{service.document_id}/parse"
        )
    assert response.status_code == 202
    assert response.json()["data"]["status"] == "IN_PROGRESS"
    worker.assert_awaited_once_with(service.document_id)
