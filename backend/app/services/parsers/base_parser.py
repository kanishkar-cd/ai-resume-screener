from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.exceptions import AppException
from app.schemas.parsed_document import ParserEngineEnum


class UnsupportedFormatException(AppException):
    status_code = 400
    error_code = "UNSUPPORTED_PARSER_FORMAT"
    default_message = "No parser is registered for this document format."


class DocumentParsingException(AppException):
    status_code = 500
    error_code = "PARSING_EXECUTION_FAILED"
    default_message = "Document parsing failed."


class CorruptedFileException(AppException):
    status_code = 422
    error_code = "CORRUPTED_DOCUMENT_FILE"
    default_message = "The document is corrupted or unreadable."


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    raw_text: str
    page_count: int | None
    parser_engine: ParserEngineEnum
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseParser(ABC):
    """Synchronous parser interface suitable for thread or worker execution."""

    @abstractmethod
    def parse(self, file_path: Path) -> ExtractionResult:
        """Extract text and deterministic metadata from a physical file."""
