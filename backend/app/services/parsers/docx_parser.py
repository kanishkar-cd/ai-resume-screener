from pathlib import Path

from docx import Document

from app.schemas.parsed_document import ParserEngine
from app.services.parsers.base import ParseOutput


def parse_docx(path: Path) -> ParseOutput:
    document = Document(str(path))
    paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
    raw_text = "\n".join(paragraphs)
    return ParseOutput(
        raw_text=raw_text,
        page_count=None,
        parser_engine=ParserEngine.PYTHON_DOCX,
    )
