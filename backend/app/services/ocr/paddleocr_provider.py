import io
from typing import Any
import structlog

from app.services.ocr.base import BaseOCRProvider

logger = structlog.get_logger(__name__)


class PaddleOCRProvider(BaseOCRProvider):
    """PaddleOCR implementation for image text extraction."""

    def __init__(self, languages: list[str] | None = None) -> None:
        langs = languages or ["en"]
        self.lang = langs[0] if langs else "en"
        self._ocr: Any = None

    @property
    def ocr(self) -> Any:
        if self._ocr is None:
            logger.info("initializing_paddleocr_engine", lang=self.lang)
            try:
                import os
                os.environ["FLAGS_use_mkldnn"] = "0"
                try:
                    import paddle
                    paddle.set_flags({"FLAGS_use_mkldnn": False})
                except Exception:
                    pass

                from paddleocr import PaddleOCR  # Lazy import to keep startup fast

                try:
                    self._ocr = PaddleOCR(lang=self.lang, enable_mkldnn=False)
                except Exception:
                    self._ocr = PaddleOCR(lang=self.lang)
            except Exception as exc:
                logger.exception("paddleocr_initialization_failed", error=str(exc))
                raise RuntimeError(f"Failed to initialize PaddleOCR engine: {exc}") from exc
        return self._ocr

    def extract_text_from_image(self, image_bytes: bytes) -> str:
        if not image_bytes:
            return ""
        try:
            import numpy as np
            from PIL import Image

            logger.info("paddleocr_executing_on_image", image_bytes_len=len(image_bytes))
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_np = np.array(image)
            try:
                result = self.ocr.ocr(img_np)
            except Exception:
                result = self.ocr.predict(img_np)

            if not result:
                logger.warning("paddleocr_returned_empty_result")
                return ""

            extracted_lines: list[str] = []
            res_items = list(result) if not isinstance(result, list) else result

            for page_res in res_items:
                if isinstance(page_res, dict):
                    rec_texts = page_res.get("rec_texts") or page_res.get("rec_text") or []
                    if isinstance(rec_texts, (list, tuple)):
                        for text in rec_texts:
                            if text and str(text).strip():
                                extracted_lines.append(str(text).strip())
                elif isinstance(page_res, list):
                    for line in page_res:
                        if isinstance(line, (list, tuple)) and len(line) >= 2 and line[1]:
                            if isinstance(line[1], (list, tuple)) and line[1]:
                                text = str(line[1][0]).strip()
                            else:
                                text = str(line[1]).strip()
                            if text:
                                extracted_lines.append(text)

            extracted_text = "\n".join(extracted_lines)
            logger.info(
                "paddleocr_executed_successfully",
                extracted_lines_count=len(extracted_lines),
                extracted_text_len=len(extracted_text),
            )
            return extracted_text
        except Exception as exc:
            logger.exception("paddleocr_extraction_failed", error=str(exc))
            raise RuntimeError(f"PaddleOCR text extraction failed: {exc}") from exc
