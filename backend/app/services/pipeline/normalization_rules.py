from __future__ import annotations
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any


from app.services.pipeline.canonical_dictionaries import RULESET_VERSION


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip())


def comparison_key(value: str) -> str:
    return clean_text(value).casefold()


def stable_unique(values: list[str], audit: NormalizationAudit | None = None) -> list[str]:
    seen: set[str] = set()
    result = []
    removed = 0
    for value in values:
        cleaned = clean_text(value)
        key = cleaned.casefold()
        if cleaned:
            if key not in seen:
                seen.add(key)
                result.append(cleaned)
            else:
                removed += 1
    if audit and removed > 0:
        audit.record_duplicates_removed(removed)
    return result


def normalize_company(value: str | None, audit: NormalizationAudit) -> str | None:
    if not value:
        return None
    source = clean_text(value)
    canonical = re.sub(r"\bCorp\.?$", "Corporation", source, flags=re.I)
    canonical = re.sub(r"\bPvt\.?\s*Ltd\.?$", "Private Limited", canonical, flags=re.I)
    canonical = re.sub(r"\bLtd\.?$", "Limited", canonical, flags=re.I)
    rule = "company_legal_suffix" if canonical != source else "preserved_unknown"
    audit.record("companies", source, canonical, rule, 1.0)
    return canonical


_DATE_FORMATS = (
    ("%Y-%m-%d", "%Y-%m-%d"),
    ("%Y-%m", "%Y-%m"),
    ("%m/%Y", "%Y-%m"),
    ("%Y", "%Y"),
    ("%b %Y", "%Y-%m"),
    ("%B %Y", "%Y-%m"),
)


def normalize_date(value: str | None, field: str, audit: NormalizationAudit) -> tuple[str | None, bool]:
    if not value:
        return None, False
    source = clean_text(value)
    if source.casefold() in {"present", "current", "now"}:
        audit.record(field, source, None, "current_date", 1.0)
        return None, True
    for date_format, output_format in _DATE_FORMATS:
        try:
            canonical = datetime.strptime(source, date_format).strftime(output_format)
            audit.record(field, source, canonical, "date_format", 1.0)
            return canonical, False
        except ValueError:
            continue
    audit.record(field, source, source, "preserved_unknown", 1.0)
    return source, False


def normalize_phone(value: str | None, audit: NormalizationAudit) -> str | None:
    if not value:
        return None
    source = clean_text(value)
    digits = re.sub(r"\D", "", source)
    if (source.startswith("+") or len(digits) >= 10) and 8 <= len(digits) <= 15:
        canonical = f"+{digits}" if not source.startswith("+") and len(digits) == 10 else (f"+{digits}" if source.startswith("+") else source)
        audit.record("phone", source, canonical, "e164_format", 1.0)
        return canonical
    audit.record("phone", source, source, "preserved_unknown", 1.0)
    return source



class NormalizationAudit:
    def __init__(self) -> None:
        self.changes: list[dict[str, str | None]] = []
        self.warnings: list[str] = []
        self._scores: dict[str, list[float]] = {}
        self.aliases_resolved: int = 0
        self.duplicates_removed: int = 0
        self.fields_normalized: set[str] = set()

    def record(self, field: str, source: str | None, canonical: str | None, rule: str, confidence: float) -> None:
        self._scores.setdefault(field, []).append(confidence)
        self.fields_normalized.add(field)
        if source != canonical:
            self.changes.append({"field": field, "source": source, "canonical": canonical, "rule": rule})
            if "alias" in rule or rule in {"exact_canonical", "email_lowercase", "e164_format", "company_legal_suffix", "date_format"}:
                self.aliases_resolved += 1
        # Do not emit warnings for valid preserved unknown values for standard fields
        if rule == "preserved_unknown" and source and field not in {"companies", "phone", "certifications", "locations", "email", "skills", "job_titles", "keywords"}:
            self.warnings.append(f"No canonical alias for {field}: {source}")

    def record_duplicates_removed(self, count: int) -> None:
        self.duplicates_removed += count

    def metadata(self) -> dict[str, Any]:
        return {
            "ruleset_version": RULESET_VERSION,
            "normalized_at": datetime.now(UTC),
            "changes": self.changes,
            "warnings": stable_unique(self.warnings),
            "field_confidence": {field: round(sum(scores) / len(scores), 2) for field, scores in self._scores.items()},
            "aliases_resolved": self.aliases_resolved,
            "duplicates_removed": self.duplicates_removed,
            "fields_normalized": sorted(list(self.fields_normalized)),
        }


_CATEGORY_LABEL_PREFIX = re.compile(
    r"^(?:frontend|backend|database|databases|engineering|tools|tooling|languages|programming\s+languages|frameworks|libraries|devops|cloud|infrastructure|testing|qa|platforms|methodologies|architecture|security|storage|monitoring|web|mobile|data|analytics|core|technical|key|skills?|other)\s*:\s*",
    re.I,
)


def canonicalize(value: str | None, aliases: dict[str, str], field: str, audit: NormalizationAudit) -> str | None:
    if not value or not clean_text(value):
        return None
    cleaned = clean_text(value)
    cleaned = _CATEGORY_LABEL_PREFIX.sub("", cleaned).strip()
    if not cleaned:
        return None
    canonical = aliases.get(comparison_key(cleaned))
    if canonical:
        audit.record(field, cleaned, canonical, "exact_canonical" if cleaned == canonical else f"{field}_alias", 1.0)
        return canonical
    audit.record(field, cleaned, cleaned, "preserved_unknown", 1.0)
    return cleaned


def normalize_list(values: list[str], aliases: dict[str, str], field: str, audit: NormalizationAudit) -> list[str]:
    return stable_unique([canonical for value in values if (canonical := canonicalize(value, aliases, field, audit))], audit=audit)


def normalize_company(value: str | None, audit: NormalizationAudit) -> str | None:
    if not value:
        return None
    source = clean_text(value)
    if not source:
        return None
    # Reject invalid company tokens: Present, dates, durations, headings, or long sentences
    if re.match(r"^(?:present|current|now|till\s*date|to\s*date|continuous)$", source, flags=re.I):
        return None
    if re.match(r"^(?:(?:19|20)\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d+\s*months?|\d+\s*years?).*", source, flags=re.I):
        return None
    if re.match(r"^(?:experience|work\s*experience|employment\s*history|professional\s*experience|projects?|technical\s*projects?|education|summary|skills?|certifications?|responsibilities|achievements)$", source, flags=re.I):
        return None
    if len(source.split()) > 8:
        return None
    canonical = re.sub(r"\bCorp\.?$", "Corporation", source, flags=re.I)
    canonical = re.sub(r"\bPvt\.?\s*Ltd\.?$", "Private Limited", canonical, flags=re.I)
    canonical = re.sub(r"\bLtd\.?$", "Limited", canonical, flags=re.I)
    rule = "company_legal_suffix" if canonical != source else "preserved_unknown"
    audit.record("companies", source, canonical, rule, 1.0)
    return canonical



_DATE_FORMATS = (
    ("%Y-%m-%d", "%Y-%m-%d"),
    ("%Y-%m", "%Y-%m"),
    ("%m/%Y", "%Y-%m"),
    ("%Y", "%Y"),
    ("%b %Y", "%Y-%m"),
    ("%B %Y", "%Y-%m"),
)


def normalize_date(value: str | None, field: str, audit: NormalizationAudit) -> tuple[str | None, bool]:
    if not value:
        return None, False
    source = clean_text(value)
    if source.casefold() in {"present", "current", "now"}:
        audit.record(field, source, None, "current_date", 0.95)
        return None, True

    # If date is a year range e.g. "2023 - 2027", graduation/effective date is the end year
    range_match = re.search(r"\b(?:19|20)\d{2}\s*[-–—to]+\s*((?:19|20)\d{2})\b", source)
    if range_match:
        end_yr = range_match.group(1)
        audit.record(field, source, end_yr, "date_format", 0.9)
        return end_yr, False

    for date_format, output_format in _DATE_FORMATS:
        try:
            canonical = datetime.strptime(source, date_format).strftime(output_format)
            audit.record(field, source, canonical, "date_format", 1.0 if source == canonical else 0.9)
            return canonical, False
        except ValueError:
            continue
    audit.record(field, source, source, "preserved_unknown", 0.5)
    return source, False


def _date_parts(value: str, *, end: bool = False) -> tuple[int, int]:
    parts = value.split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) >= 2 else (12 if end else 1)
    return year, month


def duration_between(start: str | None, end: str | None, current: bool) -> int | None:
    if not start or not re.fullmatch(r"\d{4}(?:-\d{2})?(?:-\d{2})?", start):
        return None
    effective_end = end or (datetime.now(UTC).strftime("%Y-%m") if current else None)
    if not effective_end or not re.fullmatch(r"\d{4}(?:-\d{2})?(?:-\d{2})?", effective_end):
        return None
    start_year, start_month = _date_parts(start)
    end_year, end_month = _date_parts(effective_end, end=True)
    months = (end_year - start_year) * 12 + end_month - start_month + 1
    return months if months >= 0 else None


_DURATION = re.compile(r"(?i)\b(\d+)(\+)?\s*(?:(?:-|–|to)\s*(\d+)\s*)?(yrs?|years?|mos?|months?)\b")


def parse_experience_requirement(value: str, audit: NormalizationAudit) -> dict[str, int | str | None] | None:
    source = clean_text(value)
    match = _DURATION.search(source)
    if not match:
        audit.record("experience_requirements", source, source, "preserved_unknown", 0.5)
        return {"minimum_months": None, "maximum_months": None, "display_value": source}
    low, plus_marker, high, unit = match.groups()
    factor = 12 if unit.casefold().startswith(("yr", "year")) else 1
    minimum, maximum = int(low) * factor, int(high) * factor if high else None
    plus = bool(plus_marker)
    if not high and not plus:
        maximum = minimum
    display = format_duration(minimum) if maximum in {None, minimum} else f"{format_duration(minimum)} - {format_duration(maximum)}"
    if plus:
        display += "+"
    audit.record("experience_requirements", source, display, "duration_pattern", 0.9)
    return {"minimum_months": minimum, "maximum_months": maximum, "display_value": display}


def format_duration(months: int | None) -> str | None:
    if months is None:
        return None
    years, remaining = divmod(months, 12)
    parts = []
    if years: parts.append(f"{years} year{'s' if years != 1 else ''}")
    if remaining: parts.append(f"{remaining} month{'s' if remaining != 1 else ''}")
    return " ".join(parts) or "0 months"


def normalize_phone(value: str | None, audit: NormalizationAudit) -> str | None:
    if not value:
        return None
    source = clean_text(value)
    
    # Reject masked numbers or placeholders (e.g. +91-XXXXXXXXXX, 98765XXXXX)
    if re.search(r"[xX]{2,}", source):
        return None
        
    digits = re.sub(r"\D", "", source)
    if len(digits) < 10 or len(digits) > 15:
        return None
        
    # Reject dummy repeating digits (e.g. 0000000000, 9999999999, 1234567890)
    if len(set(digits)) <= 2 or digits == "1234567890":
        return None

    # 10-digit Indian mobile numbers starting with 6, 7, 8, 9 -> +91XXXXXXXXXX
    if len(digits) == 10 and digits[0] in "6789" and not source.startswith("+"):
        canonical = f"+91{digits}"
        audit.record("phone", source, canonical, "e164_format", 1.0)
        return canonical

    # Already has + or standard international digits
    if source.startswith("+") and 10 <= len(digits) <= 15:
        canonical = f"+{digits}"
        audit.record("phone", source, canonical, "e164_format", 1.0)
        return canonical

    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        canonical = f"+{digits}"
        audit.record("phone", source, canonical, "e164_format", 1.0)
        return canonical

    if len(digits) == 11 and digits.startswith("1"):
        canonical = f"+{digits}"
        audit.record("phone", source, canonical, "e164_format", 1.0)
        return canonical

    canonical = f"+{digits}" if 10 <= len(digits) <= 15 else source
    audit.record("phone", source, canonical, "e164_format" if canonical.startswith("+") else "preserved_unknown", 1.0)
    return canonical


