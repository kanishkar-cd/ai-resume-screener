from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.parsed_document import ParserEngine
from app.services.parsers.base import ParseOutput
from app.services.parsers.pdf_parser import parse_pdf
from app.services.parsing_service import DocumentParseFailedException, ParsingService
from app.services.extraction_service import ExtractionService


def test_text_pdf_does_not_invoke_ocr(tmp_path: Path):
    """1. Text PDF does not invoke OCR unnecessarily."""
    pdf_file = tmp_path / "normal_text.pdf"
    
    mock_page = MagicMock()
    mock_page.get_text.return_value = "Harshini V K\nSenior Software Engineer with 5 years experience in Python and FastAPI.\nEducation: B.Tech Computer Science"
    
    mock_doc = MagicMock()
    mock_doc.__iter__.return_value = [mock_page]
    mock_doc.__len__.return_value = 1
    mock_doc.page_count = 1

    with patch("fitz.open", return_value=MagicMock(__enter__=MagicMock(return_value=mock_doc))), \
         patch("app.services.parsers.pdf_parser.OCRService") as mock_ocr_cls:
        result = parse_pdf(pdf_file)
        
        assert result.ocr_fallback_used is False
        assert result.ocr_engine is None
        assert "Senior Software Engineer" in result.raw_text
        mock_ocr_cls.assert_not_called()


def test_empty_text_pdf_invokes_ocr_fallback(tmp_path: Path):
    """2. Empty-text PDF invokes OCR fallback."""
    pdf_file = tmp_path / "scanned_image.pdf"

    mock_page = MagicMock()
    mock_page.get_text.return_value = ""  # Empty text extracted by PyMuPDF
    mock_pix = MagicMock()
    mock_pix.tobytes.return_value = b"fake_png_bytes"
    mock_page.get_pixmap.return_value = mock_pix

    mock_doc = MagicMock()
    mock_doc.__iter__.return_value = [mock_page]
    mock_doc.__len__.return_value = 1
    mock_doc.page_count = 1

    mock_ocr_instance = MagicMock()
    mock_ocr_instance.provider = MagicMock()
    mock_ocr_instance.provider.engine_name = "paddleocr"
    mock_ocr_instance.process_page_images.return_value = "Harshini V K\nSoftware Engineer\nSkills: Python, React, SQL\nExperience: 3 years"

    with patch("fitz.open", return_value=MagicMock(__enter__=MagicMock(return_value=mock_doc))), \
         patch("app.services.parsers.pdf_parser.OCRService", return_value=mock_ocr_instance):
        result = parse_pdf(pdf_file)

        assert result.ocr_fallback_used is True
        assert result.ocr_engine == "paddleocr"
        assert "Harshini V K" in result.raw_text
        mock_ocr_instance.process_page_images.assert_called_once()


@pytest.mark.asyncio
async def test_ocr_output_persisted_as_parsed_normalized_text(tmp_path: Path):
    """3. OCR output is persisted as parsed normalized_text."""
    doc_id = uuid4()
    pdf_file = tmp_path / "scanned.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake pdf")

    mock_doc_repo = MagicMock()
    mock_doc_repo.get_document = AsyncMock()
    mock_doc_repo.update_status = AsyncMock()
    mock_doc_repo.session = MagicMock()
    mock_doc_repo.session.commit = AsyncMock()
    mock_doc_repo.session.rollback = AsyncMock()

    mock_parsed_repo = MagicMock()
    mock_parsed_repo.upsert = AsyncMock()

    mock_storage = MagicMock()
    mock_storage.resolve_file.return_value = pdf_file

    mock_doc = MagicMock()
    mock_doc.processing_status = MagicMock()
    mock_doc.processing_status.value = "UPLOADED"
    mock_doc.mime_type = "application/pdf"
    mock_doc.metadata_json = {}
    mock_doc_repo.get_document.return_value = mock_doc
    mock_doc_repo.update_status.return_value = MagicMock(
        processing_status=MagicMock(value="PARSED"),
        processing_stage=MagicMock(value="INGESTION")
    )

    ocr_parse_output = ParseOutput(
        raw_text="HARSHINI V K\nComputer Science Student & Developer\nSkills: Python, FastAPI",
        page_count=1,
        parser_engine=ParserEngine.PYMUPDF,
        ocr_fallback_used=True,
        ocr_engine="paddleocr",
        original_parser="PYMUPDF",
    )

    with patch("app.services.parsing_service.parse_document_file", return_value=ocr_parse_output):
        service = ParsingService(mock_doc_repo, mock_parsed_repo, mock_storage)
        result = await service.parse_document(doc_id)

        assert result.processing_status.value == "PARSED"
        mock_parsed_repo.upsert.assert_called_once()
        create_arg = mock_parsed_repo.upsert.call_args[0][0]
        assert create_arg.raw_text == ocr_parse_output.raw_text
        assert create_arg.normalized_text == ocr_parse_output.raw_text
        
        # Check metadata update
        update_status_kwargs = mock_doc_repo.update_status.call_args[0]
        updated_meta = update_status_kwargs[2]
        assert updated_meta["ocr_fallback_used"] is True
        assert updated_meta["ocr_engine"] == "paddleocr"


@pytest.mark.asyncio
async def test_extraction_can_consume_ocr_output():
    """4. Extraction can consume OCR output."""
    from app.models.document import DocumentTypeEnum
    doc_id = uuid4()
    mock_doc = MagicMock()
    mock_doc.document_type = DocumentTypeEnum.RESUME
    
    mock_doc_repo = MagicMock()
    mock_doc_repo.get_document = AsyncMock(return_value=mock_doc)
    mock_doc_repo.update_processing = AsyncMock()
    
    mock_parsed_repo = MagicMock()
    mock_parsed_repo.get_by_document_id = AsyncMock()
    mock_parsed = MagicMock()
    mock_parsed.normalized_text = "HARSHINI V K\nEmail: harshini@example.com\nSkills: Python, React, SQL\nExperience: Software Engineer at Tech Corp"
    mock_parsed_repo.get_by_document_id.return_value = mock_parsed

    mock_ext_repo = MagicMock()
    mock_ext_repo.create_or_update_resume = AsyncMock()
    mock_ext_repo.create_or_update_job_description = AsyncMock()

    service = ExtractionService(mock_doc_repo, mock_parsed_repo, mock_ext_repo)
    result = await service.extract_document_data(doc_id)

    assert result.document_id == doc_id
    assert result.processing_stage.value == "COMPLETED"
    mock_ext_repo.create_or_update_resume.assert_called_once()


def test_ocr_failure_produces_clear_processing_error(tmp_path: Path):
    """5. OCR failure produces a clear processing error rather than silently continuing."""
    pdf_file = tmp_path / "blank.pdf"

    mock_page = MagicMock()
    mock_page.get_text.return_value = ""  # Empty text
    mock_pix = MagicMock()
    mock_pix.tobytes.return_value = b"fake_png"
    mock_page.get_pixmap.return_value = mock_pix

    mock_doc = MagicMock()
    mock_doc.__iter__.return_value = [mock_page]
    mock_doc.__len__.return_value = 1
    mock_doc.page_count = 1

    mock_ocr_instance = MagicMock()
    mock_ocr_instance.process_page_images.return_value = ""  # OCR returns empty text too

    with patch("fitz.open", return_value=MagicMock(__enter__=MagicMock(return_value=mock_doc))), \
         patch("app.services.parsers.pdf_parser.OCRService", return_value=mock_ocr_instance):
        with pytest.raises(RuntimeError) as exc_info:
            parse_pdf(pdf_file)
        
        assert "OCR fallback both produced empty text" in str(exc_info.value)
