from typing import Any
import structlog

from app.services.ocr.base import BaseOCRProvider

logger = structlog.get_logger(__name__)


class EasyOCRProvider(BaseOCRProvider):
    """EasyOCR implementation for image text extraction."""

    def __init__(self, languages: list[str] | None = None) -> None:
        self.languages = languages or ["en"]
        self._reader: Any = None

    @property
    def reader(self) -> Any:
        if self._reader is None:
            logger.info("initializing_easyocr_reader", languages=self.languages)
            import easyocr  # Lazy import to keep startup fast

            self._reader = easyocr.Reader(self.languages, gpu=False)
        return self._reader

    def extract_text_from_image(self, image_bytes: bytes) -> str:
        if not image_bytes:
            return ""
        try:
            results = self.reader.readtext(image_bytes, detail=0)
            if isinstance(results, list):
                return "\n".join(str(item) for item in results)
            return str(results)
        except Exception as exc:
            logger.exception("easyocr_text_extraction_failed", error=str(exc))
            raise RuntimeError(f"EasyOCR text extraction failed: {exc}") from exc
