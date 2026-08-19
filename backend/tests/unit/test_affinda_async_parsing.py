import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.services.affinda_service import AffindaService, AffindaError
from app.services.jd_extraction_service import JDExtractionService


@pytest.mark.asyncio
async def test_affinda_async_parsing_and_polling(monkeypatch):
    """Test that Affinda parse omits wait=true and polls if not immediately ready."""
    service = AffindaService()
    
    post_response_mock = MagicMock()
    post_response_mock.status_code = 201
    post_response_mock.json.return_value = {
        "identifier": "doc_12345",
        "meta": {"ready": False},
    }
    
    get_response_mock = MagicMock()
    get_response_mock.status_code = 200
    get_response_mock.json.return_value = {
        "identifier": "doc_12345",
        "data": {"jobTitle": "Software Engineer", "rawText": "Job description text..."},
        "meta": {"ready": True, "failed": False},
    }
    
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, headers=None, files=None, data=None):
            # Assert wait parameter is NOT in data payload
            assert "wait" not in (data or {})
            assert data.get("compact") == "true"
            return post_response_mock
        async def get(self, url, headers=None):
            assert "doc_12345" in url
            return get_response_mock

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    class FakePath:
        def read_bytes(self):
            return b"%PDF-1.4 test"

    result = await service.parse_job_description(FakePath(), "test.pdf", "application/pdf")
    assert result["data"]["jobTitle"] == "Software Engineer"
    assert result["meta"]["ready"] is True


@pytest.mark.asyncio
async def test_jd_extraction_reuses_cached_affinda_payload(monkeypatch):
    """Test that JDExtractionService reuses cached affinda_payload and does NOT call Affinda again."""
    from app.models.document import DocumentTypeEnum

    doc_id = uuid4()
    
    class FakeDocument:
        id = doc_id
        document_type = DocumentTypeEnum.JOB_DESCRIPTION
        processing_status = MagicMock()
        processing_status.value = "PARSED"
        metadata_json = {
            "affinda_payload": {
                "data": {
                    "jobTitle": "Data Engineer",
                    "skills": [{"name": "Python"}, {"name": "SQL"}],
                },
                "meta": {"identifier": "cached_doc_99"},
            }
        }


    class FakeParsedDoc:
        raw_text = "Parsed raw text"
        word_count = 100

    class FakeDocRepo:
        async def get_document(self, did): return FakeDocument()

    class FakeParsedRepo:
        async def get_by_document_id(self, did): return FakeParsedDoc()

    class FakeExtractedRepo:
        async def upsert(self, payload, commit=False, refresh=False): pass

    affinda_called = False
    class MockAffindaService:
        configured = True
        async def parse_job_description(self, *args, **kwargs):
            nonlocal affinda_called
            affinda_called = True
            raise RuntimeError("Should not be called!")

    service = JDExtractionService(
        document_repository=FakeDocRepo(),
        parsed_repository=FakeParsedRepo(),
        extracted_repository=FakeExtractedRepo(),
        affinda_service=MockAffindaService(),
    )
    monkeypatch.setattr(service, "_set_status", AsyncMock())

    result = await service.extract_document(doc_id)
    assert affinda_called is False
    assert result.processing_status.value == "COMPLETED"
