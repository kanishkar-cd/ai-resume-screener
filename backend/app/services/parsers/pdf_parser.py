from pathlib import Path

# pyrefly: ignore [missing-import]
import fitz
# pyrefly: ignore [missing-import]
import structlog

from app.schemas.parsed_document import ParserEngine
from app.services.ocr.ocr_service import OCRService
from app.services.parsers.base import ParseOutput

logger = structlog.get_logger(__name__)

MIN_TEXT_THRESHOLD_CHARS = 10
MIN_TEXT_THRESHOLD_WORDS = 2


def parse_pdf(path: Path) -> ParseOutput:
    pages: list[str] = []
    page_count: int | None = None
    try:
        with fitz.open(path) as document:
            pages = [page.get_text("text") for page in document]
            page_count = len(document) if hasattr(document, "__len__") else getattr(document, "page_count", 0)
    except Exception as exc:
        logger.warning("pymupdf_text_extraction_error", path=str(path), error=str(exc))

    raw_text = "\n".join(pages).strip()
    words = raw_text.split()

    if len(raw_text) >= MIN_TEXT_THRESHOLD_CHARS and len(words) >= MIN_TEXT_THRESHOLD_WORDS:
        return ParseOutput(
            raw_text=raw_text,
            page_count=page_count,
            parser_engine=ParserEngine.PYMUPDF,
            ocr_fallback_used=False,
            ocr_engine=None,
            original_parser="PYMUPDF",
        )

    logger.info(
        "pdf_text_below_threshold_invoking_ocr",
        path=str(path),
        extracted_char_count=len(raw_text),
        extracted_word_count=len(words),
    )

    # Render PDF page(s) to images for OCR
    images: list[bytes] = []
    try:
        with fitz.open(path) as document:
            page_count = len(document) if hasattr(document, "__len__") else getattr(document, "page_count", 0)
            for page in document:
                pix = page.get_pixmap(dpi=150)
                images.append(pix.tobytes("png"))
    except Exception as exc:
        logger.exception("pdf_page_image_rendering_failed", path=str(path), error=str(exc))
        raise RuntimeError(f"Failed to render PDF pages to images for OCR fallback: {exc}") from exc

    if not images:
        raise RuntimeError("PDF contains no readable pages to render for OCR.")

    ocr_service = OCRService()
    ocr_engine_name = getattr(
        ocr_service.provider, "engine_name", type(ocr_service.provider).__name__.lower().replace("provider", "")
    )

    ocr_text = ocr_service.process_page_images(images).strip()
    if not ocr_text:
        raise RuntimeError("PDF text extraction and OCR fallback both produced empty text.")

    return ParseOutput(
        raw_text=ocr_text,
        page_count=page_count,
        parser_engine=ParserEngine.PYMUPDF,
        ocr_fallback_used=True,
        ocr_engine=ocr_engine_name,
        original_parser="PYMUPDF",
    )
