import re
from dataclasses import dataclass

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
HORIZONTAL_WHITESPACE = re.compile(r"[^\S\n]+")
EXCESSIVE_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    normalized_text: str
    language: str
    word_count: int
    character_count: int


def normalize_text(raw_text: str) -> NormalizationResult:
    """Normalize extracted text and calculate deterministic text metadata."""
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = CONTROL_CHARACTERS.sub("", normalized)
    normalized = HORIZONTAL_WHITESPACE.sub(" ", normalized)
    normalized = "\n".join(line.strip() for line in normalized.split("\n"))
    normalized = EXCESSIVE_BLANK_LINES.sub("\n\n", normalized).strip()
    words = normalized.split()
    try:
        language = detect(normalized) if len(words) >= 3 and len(normalized) >= 20 else "en"
    except LangDetectException:
        language = "en"
    return NormalizationResult(
        normalized_text=normalized,
        language=language,
        word_count=len(words),
        character_count=len(normalized),
    )
