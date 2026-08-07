from pathlib import Path
import fitz
import structlog

from app.core.config import get_settings
from app.schemas.parsed_document import ParserEngineEnum
from app.services.ocr.ocr_service import OCRService
from app.services.parsers.base_parser import (
    BaseParser,
    CorruptedFileException,
    ExtractionResult,
)

logger = structlog.get_logger(__name__)


class PDFParser(BaseParser):
    """Extract PDF text using PyMuPDF with automated OCR fallback for scanned PDFs."""

    def __init__(self, ocr_service: OCRService | None = None) -> None:
        self._ocr_service = ocr_service

    @property
    def ocr_service(self) -> OCRService:
        if self._ocr_service is None:
            self._ocr_service = OCRService()
        return self._ocr_service

    def parse(self, file_path: Path) -> ExtractionResult:
        try:
            with fitz.open(file_path) as document:
                if document.needs_pass:
                    raise CorruptedFileException("Encrypted PDFs are not supported.")

                # 1. Primary extraction via PyMuPDF
                page_texts = [page.get_text("text") for page in document]
                raw_text = "\n".join(page_texts)
                word_count = len(raw_text.split())

                settings = get_settings()
                ocr_used = False
                ocr_engine = None

                # 2. Scanned / Image-based PDF detection and OCR fallback
                if (not raw_text.strip() or word_count == 0) and settings.ENABLE_OCR_FALLBACK:
                    logger.info("scanned_pdf_detected_invoking_ocr", file_path=str(file_path))
                    page_images: list[bytes] = []
                    dpi = getattr(settings, "OCR_DPI", 200)

                    for page in document:
                        pix = page.get_pixmap(dpi=dpi)
                        page_images.append(pix.tobytes("png"))

                    raw_text = self.ocr_service.process_page_images(page_images)
                    ocr_used = True
                    ocr_engine = settings.OCR_ENGINE.upper()

                metadata = {
                    "parser_engine": ParserEngineEnum.PYMUPDF.value,
                    "ocr_used": ocr_used,
                    "ocr_engine": ocr_engine,
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
