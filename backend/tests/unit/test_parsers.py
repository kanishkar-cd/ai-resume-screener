from pathlib import Path

import fitz
import pytest
from docx import Document

from app.schemas.parsed_document import ParserEngineEnum
from app.services.parsers.base_parser import CorruptedFileException
from app.services.parsers.docx_parser import DocxParser
from app.services.parsers.pdf_parser import PDFParser
from app.services.parsers.txt_parser import TxtParser


def test_pdf_parser_extracts_text_and_page_count(tmp_path: Path) -> None:
    path = tmp_path / "resume.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Senior Python Engineer")
        document.save(path)

    result = PDFParser().parse(path)

    assert "Senior Python Engineer" in result.raw_text
    assert result.page_count == 1
    assert result.parser_engine == ParserEngineEnum.PYMUPDF


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
