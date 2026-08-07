from typing import Sequence

import structlog

from app.core.config import get_settings
from app.services.ocr.base import BaseOCRProvider
from app.services.ocr.factory import OCRProviderFactory

logger = structlog.get_logger(__name__)


class OCRService:
    """Orchestrate OCR text extraction over page image streams."""

    def __init__(self, provider: BaseOCRProvider | None = None) -> None:
        if provider is not None:
            self.provider = provider
        else:
            settings = get_settings()
            self.provider = OCRProviderFactory.create(
                engine_name=settings.OCR_ENGINE,
                languages=settings.OCR_LANGUAGES,
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
            page_text = self.provider.extract_text_from_image(image_bytes)
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
