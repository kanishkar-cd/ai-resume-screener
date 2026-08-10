from dataclasses import dataclass

from app.schemas.parsed_document import ParserEngine


@dataclass(frozen=True, slots=True)
class ParseOutput:
    raw_text: str
    page_count: int | None
    parser_engine: ParserEngine


def text_metrics(raw_text: str) -> tuple[int, int]:
    """Return (word_count, character_count) for extracted text."""
    character_count = len(raw_text)
    words = raw_text.split()
    return len(words), character_count
