from pathlib import Path

import fitz

from app.schemas.parsed_document import ParserEngine
from app.services.parsers.base import ParseOutput


def parse_pdf(path: Path) -> ParseOutput:
    with fitz.open(path) as document:
        pages = [page.get_text("text") for page in document]
        page_count = document.page_count
    raw_text = "\n".join(pages)
    return ParseOutput(
        raw_text=raw_text,
        page_count=page_count,
        parser_engine=ParserEngine.PYMUPDF,
    )
