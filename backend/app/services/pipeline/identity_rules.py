from __future__ import annotations

import re
import unicodedata
from typing import Any

# pyrefly: ignore [missing-import]
import phonenumbers

# Generic titles and non-names that should be discarded
GENERIC_NON_NAMES = frozenset({
    "resume",
    "resumes",
    "curriculum vitae",
    "curriculum-vitae",
    "curriculum_vitae",
    "cv",
    "biodata",
    "bio-data",
    "bio_data",
    "profile",
    "applicant",
    "candidate",
    "candidate profile",
    "n/a",
    "na",
    "null",
    "none",
    "unknown",
    "name",
    "candidate name",
    "your name",
    "full name",
    "first name",
    "last name",
})

# Prefixes to strip if at the very beginning of a name
NAME_PREFIXES = re.compile(
    r"^(?:(?:dr|mr|mrs|ms|prof|rev|shri|smt)\.?)\s+",
    re.IGNORECASE,
)

# Professional degree/honorific suffixes to strip if at the end of a name
NAME_SUFFIXES = re.compile(
    r"(?:,\s*|\s+)(?:ph\.?d|m\.?d|m\.?b\.?a|esq\.?|b\.?tech|m\.?tech|b\.?e\.?|m\.?e\.?|b\.?sc|m\.?sc)$",
    re.IGNORECASE,
)

# Standard basic email regex: RFC 5322 simplified, safe against ReDoS
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$"
)


def normalize_email_address(value: Any) -> tuple[str | None, dict[str, Any]]:
    """Normalize email: trim whitespace, lowercase, and validate format.

    Preserves original value in returned metadata.
    Returns:
        (canonical_email, metadata_dict)
    """
    original = value if value is not None else None
    if not isinstance(value, str):
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "missing_or_non_string",
        }

    trimmed = value.strip()
    if not trimmed:
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "empty_string",
        }

    canonical = trimmed.lower()

    # Reject if spaces within, missing @, or invalid structure
    if " " in canonical or not EMAIL_REGEX.match(canonical):
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "malformed_email",
        }

    return canonical, {
        "original": original,
        "canonical": canonical,
        "is_valid": True,
    }


def normalize_phone_number(
    value: Any,
    default_region: str = "IN",
) -> tuple[str | None, dict[str, Any]]:
    """Normalize phone number using phonenumbers library preserving country code.

    Preserves original value in returned metadata.
    Returns:
        (canonical_e164, metadata_dict)
    """
    original = value if value is not None else None
    if isinstance(value, dict):
        value = value.get("formattedNumber") or value.get("rawText") or value.get("raw")

    if not isinstance(value, str):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(int(value))
        else:
            return None, {
                "original": original,
                "canonical": None,
                "is_valid": False,
                "reason": "missing_or_non_string",
            }

    raw = unicodedata.normalize("NFKC", value).strip()
    if not raw:
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "empty_string",
        }

    # Reject masked numbers (e.g. +91 XXXXX XXXXX)
    if re.search(r"[xX]{2,}", raw):
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "masked_number",
        }

    # Extract digits to check trivial dummy patterns
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7 or len(digits) > 15 or len(set(digits)) <= 2 or digits == "1234567890":
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "dummy_or_invalid_digits",
        }

    # Handle standard European/international call prefix "00" (e.g. "0044..." -> "+44...")
    clean_num = raw
    if clean_num.startswith("00") and len(clean_num) > 2 and clean_num[2].isdigit():
        clean_num = "+" + clean_num[2:].strip()

    # Determine region: if explicitly prefixed with '+', parse with region=None
    parse_region = None if clean_num.startswith("+") else default_region

    try:
        parsed = phonenumbers.parse(clean_num, parse_region)
        if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
            return None, {
                "original": original,
                "canonical": None,
                "is_valid": False,
                "reason": "invalid_phone_number",
                "country_code": getattr(parsed, "country_code", None),
            }

        canonical = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        region_code = phonenumbers.region_code_for_number(parsed)

        return canonical, {
            "original": original,
            "canonical": canonical,
            "is_valid": True,
            "country_code": parsed.country_code,
            "national_number": str(parsed.national_number),
            "region_code": region_code,
        }
    except phonenumbers.NumberParseException as exc:
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": f"unparseable_phone: {exc.error_type}",
        }


def _format_name_word(word: str) -> str:
    """Format an individual name word with casing, hyphen, apostrophe, and initial handling."""
    if not word:
        return ""

    # Preserve uppercase initials (e.g. "CS", "RK", "A.") or Roman numerals ("II", "III", "IV")
    bare = word.strip(".")
    # Single-letter word is always an initial (e.g. "k." -> "K.", "a" -> "A")
    if len(bare) == 1:
        return bare.upper() + ("." if word.endswith(".") else "")

    # Preserve initials (e.g. "CS", "RK", "cs", "A.") or Roman numerals ("II", "III", "IV")
    is_initial = (
        len(bare) <= 2
        and (word.isupper() or "." in word or not any(c in "aeiouy" for c in bare.lower()))
    )
    if is_initial or word.upper() in {"II", "III", "IV", "V", "VI", "JR", "SR"}:
        if word.upper() in {"JR", "SR"} and not word.endswith("."):
            return word.capitalize() + "."
        return word.upper()

    # Handle hyphenated names: "mary-jane" -> "Mary-Jane"
    if "-" in word:
        parts = word.split("-")
        return "-".join(_format_name_word(p) for p in parts)

    # Handle apostrophes: "o'connor" -> "O'Connor", "d'angelo" -> "D'Angelo"
    if "'" in word:
        parts = word.split("'")
        return "'".join(_format_name_word(p) for p in parts)

    # Standard capitalize (handles "john" -> "John", "DOE" -> "Doe")
    return word.capitalize()


def normalize_candidate_name(value: Any) -> tuple[str | None, dict[str, Any]]:
    """Normalize candidate name: strip whitespace, remove unwanted punctuation, handle case & initials.

    Preserves original value in returned metadata.
    Returns:
        (canonical_name, metadata_dict)
    """
    original = value if value is not None else None
    if not isinstance(value, str):
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "missing_or_non_string",
        }

    raw = unicodedata.normalize("NFKC", value).strip()
    if not raw:
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "empty_string",
        }

    # Early rejection of generic document headings / placeholder names
    if raw.casefold() in GENERIC_NON_NAMES:
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "generic_document_title",
        }

    # Remove email addresses or URLs or phone numbers if accidentally concatenated
    cleaned = re.sub(r"\S+@\S+", "", raw)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"\b\d{7,}\b", "", cleaned)

    # Remove brackets/parentheses and their content: "Mary Jane (MJ)" -> "Mary Jane"
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"\[[^\]]*\]", "", cleaned)

    # Strip prefixes and suffixes
    cleaned = NAME_PREFIXES.sub("", cleaned).strip()
    cleaned = NAME_SUFFIXES.sub("", cleaned).strip()

    # Strip unwanted symbols, keeping letters, spaces, hyphens, apostrophes, and periods for initials
    cleaned = re.sub(r"[^\w\s.\-']", " ", cleaned)
    # Collapse whitespace and strip surrounding punctuation (except single letter initial with dot)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_',")
    # Strip trailing period only if not preceded by a single letter initial
    cleaned = re.sub(r"(?<!\b[a-zA-Z])\.$", "", cleaned).strip()

    # Reject if no letters, or length < 2, or pure digits
    if not re.search(r"[a-zA-Z]", cleaned) or len(cleaned) < 2:
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "no_valid_name_characters",
        }

    if cleaned.casefold() in GENERIC_NON_NAMES:
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "generic_document_title",
        }

    # Format words
    words = cleaned.split()
    if not words or len(words) > 7:
        return None, {
            "original": original,
            "canonical": None,
            "is_valid": False,
            "reason": "unusual_word_count",
        }

    formatted_words = [_format_name_word(w) for w in words]
    canonical = " ".join(formatted_words)[:255]

    return canonical, {
        "original": original,
        "canonical": canonical,
        "is_valid": True,
    }


def normalize_candidate_identity(
    candidate_name: Any = None,
    email: Any = None,
    phone: Any = None,
    default_region: str = "IN",
) -> dict[str, Any]:
    """Unified identity normalization for name, email, and phone preserving originals and metadata."""
    canonical_name, name_meta = normalize_candidate_name(candidate_name)
    canonical_email, email_meta = normalize_email_address(email)
    canonical_phone, phone_meta = normalize_phone_number(phone, default_region=default_region)

    return {
        "candidate_name": canonical_name,
        "email": canonical_email,
        "phone": canonical_phone,
        "raw_candidate_name": candidate_name,
        "raw_email": email,
        "raw_phone": phone,
        "identity_metadata": {
            "candidate_name": name_meta,
            "email": email_meta,
            "phone": phone_meta,
        },
    }
