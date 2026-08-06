from pathlib import Path
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from app.schemas.parsed_document import ParserEngineEnum
from app.services.parsers.base_parser import (
    BaseParser,
    CorruptedFileException,
    ExtractionResult,
)


class DocxParser(BaseParser):
    """Extract paragraphs and table-cell text using python-docx."""

    def parse(self, file_path: Path) -> ExtractionResult:
        try:
            document = Document(file_path)
            parts = [paragraph.text for paragraph in document.paragraphs]
            for table in document.tables:
                for row in table.rows:
                    parts.append("\t".join(cell.text for cell in row.cells))
            return ExtractionResult(
                raw_text="\n".join(parts),
                page_count=None,
                parser_engine=ParserEngineEnum.PYTHON_DOCX,
                metadata={
                    "paragraph_count": len(document.paragraphs),
                    "table_count": len(document.tables),
                },
            )
        except (PackageNotFoundError, BadZipFile, KeyError, ValueError) as exc:
            raise CorruptedFileException("The DOCX is corrupted or unreadable.") from exc
