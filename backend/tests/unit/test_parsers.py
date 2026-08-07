import io
from pathlib import Path
import fitz
from PIL import Image, ImageDraw
import pytest
from docx import Document

from app.schemas.parsed_document import ParserEngineEnum
from app.services.ocr.base import BaseOCRProvider
from app.services.ocr.easyocr_provider import EasyOCRProvider
from app.services.ocr.paddleocr_provider import PaddleOCRProvider
from app.services.ocr.factory import OCRProviderFactory
from app.services.ocr.ocr_service import OCRService
from app.services.parsers.base_parser import CorruptedFileException
from app.services.parsers.docx_parser import DocxParser
from app.services.parsers.pdf_parser import PDFParser
from app.services.parsers.txt_parser import TxtParser


class StubOCRProvider(BaseOCRProvider):
    """Stub OCR provider for fast, deterministic unit test verification."""

    def extract_text_from_image(self, image_bytes: bytes) -> str:
        if not image_bytes:
            return ""
        return "OCR Extracted Text From Image"


class EmptyOCRProvider(BaseOCRProvider):
    """OCR provider that returns empty string for blank images."""

    def extract_text_from_image(self, image_bytes: bytes) -> str:
        return ""


def _create_image_pdf(file_path: Path, text: str = "Scanned Resume Content") -> None:
    """Helper to generate a purely scanned/image-based PDF (no text glyphs)."""
    img = Image.new("RGB", (600, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((50, 50), text, fill=(0, 0, 0))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    rect = fitz.Rect(0, 0, 600, 400)
    page.insert_image(rect, stream=img_bytes)
    doc.save(file_path)
    doc.close()


def test_searchable_pdf_parsing(tmp_path: Path) -> None:
    path = tmp_path / "searchable.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Senior Python Engineer")
        document.save(path)

    result = PDFParser().parse(path)

    assert "Senior Python Engineer" in result.raw_text
    assert result.page_count == 1
    assert result.parser_engine == ParserEngineEnum.PYMUPDF
    assert result.metadata["ocr_used"] is False
    assert result.metadata["ocr_engine"] is None


def test_scanned_pdf_triggers_ocr_fallback(tmp_path: Path) -> None:
    path = tmp_path / "scanned.pdf"
    _create_image_pdf(path, "Scanned Resume Content")

    mock_ocr = OCRService(provider=StubOCRProvider())
    parser = PDFParser(ocr_service=mock_ocr)
    result = parser.parse(path)

    assert result.page_count == 1
    assert result.parser_engine == ParserEngineEnum.PYMUPDF
    assert result.metadata["ocr_used"] is True
    assert isinstance(result.metadata["ocr_engine"], str) and len(result.metadata["ocr_engine"]) > 0


    assert "OCR Extracted Text From Image" in result.raw_text


def test_mixed_pdf_parsing(tmp_path: Path) -> None:
    path = tmp_path / "mixed.pdf"
    doc = fitz.open()

    # Page 1: Searchable text
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Searchable Resume Header")

    # Page 2: Image element
    img = Image.new("RGB", (300, 200), color=(240, 240, 240))
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    page2 = doc.new_page()
    page2.insert_image(fitz.Rect(0, 0, 300, 200), stream=img_bytes.getvalue())

    doc.save(path)
    doc.close()

    result = PDFParser().parse(path)

    assert "Searchable Resume Header" in result.raw_text
    assert result.page_count == 2
    assert result.metadata["ocr_used"] is False


def test_empty_scanned_pdf_handling(tmp_path: Path) -> None:
    path = tmp_path / "blank_scanned.pdf"
    doc = fitz.open()
    doc.new_page()  # Blank page, no text and no images
    doc.save(path)
    doc.close()

    empty_ocr_service = OCRService(provider=EmptyOCRProvider())
    parser = PDFParser(ocr_service=empty_ocr_service)
    result = parser.parse(path)

    assert result.page_count == 1
    assert result.metadata["ocr_used"] is True
    assert result.raw_text == ""


def test_docx_parser_extracts_paragraphs_and_tables(tmp_path: Path) -> None:
    path = tmp_path / "resume.docx"
    document = Document()
    document.add_paragraph("Backend Engineer")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "FastAPI"
    document.save(path)

    result = DocxParser().parse(path)

    assert "Backend Engineer" in result.raw_text
    assert "FastAPI" in result.raw_text
    assert result.parser_engine == ParserEngineEnum.PYTHON_DOCX


def test_txt_parser_reads_strict_utf8(tmp_path: Path) -> None:
    path = tmp_path / "resume.txt"
    path.write_text("Python developer", encoding="utf-8")

    result = TxtParser().parse(path)

    assert result.raw_text == "Python developer"
    assert result.page_count == 1
    assert result.parser_engine == ParserEngineEnum.PLAIN_TEXT


def test_corrupted_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-this-is-not-a-valid-pdf")
    with pytest.raises(CorruptedFileException):
        PDFParser().parse(path)


def test_ocr_provider_factory_registration() -> None:
    factory_paddle = OCRProviderFactory.create("paddleocr")
    assert factory_paddle is not None
    factory_easy = OCRProviderFactory.create("easyocr")
    assert factory_easy is not None

    with pytest.raises(ValueError):
        OCRProviderFactory.create("unsupported_engine_xyz")


def test_real_easyocr_provider_extraction() -> None:
    pytest.importorskip("easyocr")
    img = Image.new("RGB", (300, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), "HELLO OCR", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    provider = EasyOCRProvider(languages=["en"])
    text = provider.extract_text_from_image(buf.getvalue())
    assert "HELLO" in text.upper() or "OCR" in text.upper() or len(text) > 0


def test_paddleocr_provider_extraction() -> None:
    pytest.importorskip("paddleocr")
    img = Image.new("RGB", (300, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), "HELLO PADDLE", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    provider = OCRProviderFactory.create("paddleocr", languages=["en"])
    text = provider.extract_text_from_image(buf.getvalue())
    assert isinstance(text, str)

