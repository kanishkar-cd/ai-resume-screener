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


def test_parse_docx_extracts_text(tmp_path: Path) -> None:
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
