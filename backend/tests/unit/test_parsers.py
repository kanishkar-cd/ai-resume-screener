from pathlib import Path

import fitz
from docx import Document

from app.schemas.parsed_document import ParserEngine
from app.services.parsers import parse_document_file
from app.services.parsers.docx_parser import parse_docx
from app.services.parsers.pdf_parser import parse_pdf


def test_parse_pdf_extracts_text(tmp_path: Path) -> None:
    path = tmp_path / "resume.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Python FastAPI Engineer")
    document.save(path)
    document.close()

    result = parse_pdf(path)
    assert result.parser_engine == ParserEngine.PYMUPDF
    assert result.page_count == 1
    assert "Python" in result.raw_text


<<<<<<< HEAD
def test_parse_docx_extracts_text(tmp_path: Path) -> None:
=======
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
>>>>>>> dba78ab0f58488ea53f75dd1d81c94f4f4f43cbb
    path = tmp_path / "resume.docx"
    document = Document()
    document.add_paragraph("Django REST experience")
    document.save(path)

    result = parse_docx(path)
    assert result.parser_engine == ParserEngine.PYTHON_DOCX
    assert result.page_count is None
    assert "Django" in result.raw_text


def test_dispatch_by_mime_type(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("plain text resume", encoding="utf-8")
    result = parse_document_file(path, "text/plain")
    assert result.parser_engine == ParserEngine.PLAIN_TEXT
