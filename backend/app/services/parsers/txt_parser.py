from pathlib import Path

from app.schemas.parsed_document import ParserEngine
from app.services.parsers.base import ParseOutput


def parse_txt(path: Path) -> ParseOutput:
    raw_text = path.read_text(encoding="utf-8")
    return ParseOutput(
        raw_text=raw_text,
        page_count=1,
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
