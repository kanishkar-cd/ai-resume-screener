from pathlib import Path

from app.schemas.parsed_document import ParserEngineEnum
from app.services.parsers.base_parser import (
    BaseParser,
    CorruptedFileException,
    ExtractionResult,
)


class TxtParser(BaseParser):
    """Read strict UTF-8 plain text documents."""

    def parse(self, file_path: Path) -> ExtractionResult:
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            raise CorruptedFileException("The text file is not valid UTF-8.") from exc
        return ExtractionResult(
            raw_text=text,
            page_count=1,
            parser_engine=ParserEngineEnum.PLAIN_TEXT,
            metadata={"encoding": "utf-8"},
        )
