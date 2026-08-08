from pathlib import Path

from app.core.exceptions import ValidationException
from app.services.parsers.base import ParseOutput
from app.services.parsers.docx_parser import parse_docx
from app.services.parsers.pdf_parser import parse_pdf
from app.services.parsers.txt_parser import parse_txt

MIME_PARSERS = {
    "application/pdf": parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": parse_docx,
    "text/plain": parse_txt,
}


class UnsupportedDocumentTypeException(ValidationException):
    error_code = "UNSUPPORTED_DOCUMENT_TYPE"
    default_message = "Only PDF, DOCX, and TXT documents can be parsed."


def parse_document_file(path: Path, mime_type: str) -> ParseOutput:
    """Dispatch to the parser matching the document MIME type."""
    parser = MIME_PARSERS.get(mime_type)
    if parser is None:
        raise UnsupportedDocumentTypeException()
    return parser(path)
