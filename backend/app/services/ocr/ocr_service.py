from typing import Sequence

import structlog

from app.core.config import get_settings
from app.services.ocr.base import BaseOCRProvider
from app.services.ocr.factory import OCRProviderFactory
from app.services.ocr.paddleocr_provider import PaddleOCRProvider

logger = structlog.get_logger(__name__)


class OCRService:
    """Orchestrate OCR text extraction over page image streams."""

    def __init__(self, provider: BaseOCRProvider | None = None) -> None:
        if provider is not None:
            self.provider = provider
        else:
            settings = get_settings()
            engine_name = getattr(settings, "OCR_ENGINE", "paddleocr") or "paddleocr"
            languages = getattr(settings, "OCR_LANGUAGES", ["en"])
            try:
                self.provider = OCRProviderFactory.create(
                    engine_name=engine_name,
                    languages=languages,
                )
            except Exception:
                logger.warning(
                    "configured_ocr_engine_failed_falling_back_to_paddleocr",
                    configured_engine=engine_name,
                )
                self.provider = OCRProviderFactory.create(
                    engine_name="paddleocr",
                    languages=languages,
                )

    def process_page_images(self, page_images: Sequence[bytes]) -> str:
        """Process page image bytes sequentially and return combined page text."""
        provider_name = type(self.provider).__name__
        logger.info(
            "ocr_service_processing_pages",
            page_count=len(page_images),
            provider=provider_name,
        )
        extracted_pages: list[str] = []
        for index, image_bytes in enumerate(page_images):
            try:
                page_text = self.provider.extract_text_from_image(image_bytes)
            except Exception as exc:
                if not isinstance(self.provider, PaddleOCRProvider):
                    logger.warning("primary_ocr_provider_failed_switching_to_paddleocr", error=str(exc))
                    self.provider = PaddleOCRProvider()
                    page_text = self.provider.extract_text_from_image(image_bytes)
                else:
                    raise

            logger.info(
                "ocr_page_processed",
                page_index=index,
                text_length=len(page_text),
                provider=provider_name,
            )
            extracted_pages.append(page_text.strip())

        combined_text = "\n\n".join(extracted_pages)
        logger.info(
            "ocr_service_completed",
            total_pages=len(page_images),
            combined_text_len=len(combined_text),
            provider=provider_name,
        )
        return combined_text
