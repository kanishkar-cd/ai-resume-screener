from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.document import DocumentTypeEnum
from app.schemas.document import ProcessingStage
from app.services.normalization_service import ExtractedDataNotFoundException, NormalizationService


class StubDocuments:
    def __init__(self, document): self.document = document; self.updates = []
    async def get_document(self, document_id): return self.document
    async def update_processing(self, document_id, stage, status, error_message=None): self.updates.append((stage, status, error_message))


class StubExtractions:
    def __init__(self, value): self.value = value
    async def get_resume_by_document_id(self, document_id): return self.value
    async def get_job_description_by_document_id(self, document_id): return self.value


class StubNormalizations:
    def __init__(self): self.resume = None
    async def create_or_update_resume(self, data): self.resume = data
    async def create_or_update_job_description(self, data): raise AssertionError


@pytest.mark.asyncio
async def test_service_selects_resume_and_transitions() -> None:
    document_id, extracted_id = uuid4(), uuid4()
    document = SimpleNamespace(id=document_id, document_type=DocumentTypeEnum.RESUME)
    extracted = SimpleNamespace(id=extracted_id, skills=["Py"], education=[], companies=[], designation=None, experience=[], phone=None, email=None, location=None, languages=[], certifications=[])
    documents, normalized = StubDocuments(document), StubNormalizations()
    response = await NormalizationService(documents, StubExtractions(extracted), normalized).normalize_document_data(document_id)
    assert normalized.resume.skills == ["Python"]
    assert response.processing_stage == ProcessingStage.COMPLETED
    assert [item[0] for item in documents.updates] == [ProcessingStage.NORMALIZATION, ProcessingStage.COMPLETED]


@pytest.mark.asyncio
async def test_service_requires_stage3_output_without_transition() -> None:
    document_id = uuid4()
    documents = StubDocuments(SimpleNamespace(id=document_id, document_type=DocumentTypeEnum.RESUME))
    with pytest.raises(ExtractedDataNotFoundException):
        await NormalizationService(documents, StubExtractions(None), StubNormalizations()).normalize_document_data(document_id)
    assert documents.updates == []
