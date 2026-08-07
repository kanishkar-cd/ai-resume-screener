from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.document import DocumentTypeEnum
from app.schemas.document import ProcessingStage
from app.services.extraction_service import ExtractionService, ParsedTextNotFoundException


class StubDocuments:
    def __init__(self, document): self.document = document; self.updates = []
    async def get_document(self, document_id): return self.document
    async def update_processing(self, document_id, stage, status, error_message=None):
        self.updates.append((stage, status, error_message))


class StubParsed:
    def __init__(self, text): self.text = text
    async def get_by_document_id(self, document_id):
        return SimpleNamespace(normalized_text=self.text) if self.text is not None else None


class StubExtraction:
    def __init__(self): self.resume = None
    async def create_or_update_resume(self, data): self.resume = data
    async def create_or_update_job_description(self, data): raise AssertionError


@pytest.mark.asyncio
async def test_extraction_service_persists_resume_and_transitions_stage() -> None:
    document_id = uuid4()
    documents = StubDocuments(SimpleNamespace(document_type=DocumentTypeEnum.RESUME))
    extracted = StubExtraction()
    service = ExtractionService(documents, StubParsed("Jane Doe\njane@example.com\nSKILLS\nPython"), extracted)
    response = await service.extract_document_data(document_id)
    assert extracted.resume.document_id == document_id
    assert response.processing_stage == ProcessingStage.COMPLETED
    assert [update[0] for update in documents.updates] == [ProcessingStage.EXTRACTION, ProcessingStage.COMPLETED]


@pytest.mark.asyncio
async def test_extraction_requires_parsed_text_without_changing_stage() -> None:
    documents = StubDocuments(SimpleNamespace(document_type=DocumentTypeEnum.RESUME))
    service = ExtractionService(documents, StubParsed(None), StubExtraction())
    with pytest.raises(ParsedTextNotFoundException):
        await service.extract_document_data(uuid4())
    assert documents.updates == []
