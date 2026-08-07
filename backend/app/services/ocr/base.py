from abc import ABC, abstractmethod


class BaseOCRProvider(ABC):
    """Abstract base class for pluggable OCR engines."""

    @abstractmethod
    def extract_text_from_image(self, image_bytes: bytes) -> str:
        """Extract text content from a single image byte stream."""
        pass
