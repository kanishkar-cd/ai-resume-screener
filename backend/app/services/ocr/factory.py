from typing import Type

from app.services.ocr.base import BaseOCRProvider
from app.services.ocr.easyocr_provider import EasyOCRProvider
from app.services.ocr.paddleocr_provider import PaddleOCRProvider


class OCRProviderFactory:
    """Factory to register and instantiate OCR providers dynamically."""

    _providers: dict[str, Type[BaseOCRProvider]] = {
        "paddleocr": PaddleOCRProvider,
        "easyocr": EasyOCRProvider,
    }

    @classmethod
    def register_provider(cls, name: str, provider_cls: Type[BaseOCRProvider]) -> None:
        cls._providers[name.lower()] = provider_cls

    @classmethod
    def create(
        cls, engine_name: str = "paddleocr", languages: list[str] | None = None
    ) -> BaseOCRProvider:
        provider_cls = cls._providers.get(engine_name.lower())
        if provider_cls is None:
            raise ValueError(f"Unsupported OCR engine provider: {engine_name}")
        return provider_cls(languages=languages)
