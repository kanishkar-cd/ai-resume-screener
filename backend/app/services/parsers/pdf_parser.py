from pathlib import Path

import fitz

from app.schemas.parsed_document import ParserEngineEnum
from app.services.parsers.base_parser import (
    BaseParser,
    CorruptedFileException,
    ExtractionResult,
)


class PDFParser(BaseParser):
    """Extract embedded PDF text with PyMuPDF; OCR is intentionally excluded."""

    def parse(self, file_path: Path) -> ExtractionResult:
        try:
            with fitz.open(file_path) as document:
                if document.needs_pass:
                    raise CorruptedFileException("Encrypted PDFs are not supported.")
                raw_text = "\n".join(page.get_text("text") for page in document)
                metadata = {
                    "pdf_version": document.metadata.get("format", ""),
                    "is_encrypted": bool(document.is_encrypted),
                }
                return ExtractionResult(
                    raw_text=raw_text,
                    page_count=document.page_count,
                    parser_engine=ParserEngineEnum.PYMUPDF,
                    metadata=metadata,
                )
        except CorruptedFileException:
            raise
        except (fitz.FileDataError, RuntimeError, ValueError) as exc:
            raise CorruptedFileException("The PDF is corrupted or unreadable.") from exc
