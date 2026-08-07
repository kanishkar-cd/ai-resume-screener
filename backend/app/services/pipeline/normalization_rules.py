import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from app.services.pipeline.canonical_dictionaries import RULESET_VERSION


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip())


def comparison_key(value: str) -> str:
    return clean_text(value).casefold()


def stable_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        cleaned = clean_text(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


class NormalizationAudit:
    def __init__(self) -> None:
        self.changes: list[dict[str, str | None]] = []
        self.warnings: list[str] = []
        self._scores: dict[str, list[float]] = {}

    def record(self, field: str, source: str | None, canonical: str | None, rule: str, confidence: float) -> None:
        self._scores.setdefault(field, []).append(confidence)
        if source != canonical or rule == "preserved_unknown":
            self.changes.append({"field": field, "source": source, "canonical": canonical, "rule": rule})
        if rule == "preserved_unknown" and source:
            self.warnings.append(f"No canonical alias for {field}: {source}")

    def metadata(self) -> dict[str, Any]:
        return {
            "ruleset_version": RULESET_VERSION,
            "normalized_at": datetime.now(UTC),
            "changes": self.changes,
            "warnings": stable_unique(self.warnings),
            "field_confidence": {field: round(sum(scores) / len(scores), 2) for field, scores in self._scores.items()},
        }


def canonicalize(value: str | None, aliases: dict[str, str], field: str, audit: NormalizationAudit) -> str | None:
    if not value or not clean_text(value):
        return None
    cleaned = clean_text(value)
    canonical = aliases.get(comparison_key(cleaned))
    if canonical:
        audit.record(field, cleaned, canonical, "exact_canonical" if cleaned == canonical else f"{field}_alias", 1.0 if cleaned == canonical else 0.95)
        return canonical
    audit.record(field, cleaned, cleaned, "preserved_unknown", 0.5)
    return cleaned


def normalize_list(values: list[str], aliases: dict[str, str], field: str, audit: NormalizationAudit) -> list[str]:
    return stable_unique([canonical for value in values if (canonical := canonicalize(value, aliases, field, audit))])


def normalize_company(value: str | None, audit: NormalizationAudit) -> str | None:
    if not value:
        return None
    source = clean_text(value)
    canonical = re.sub(r"\bCorp\.?$", "Corporation", source, flags=re.I)
    canonical = re.sub(r"\bPvt\.?\s*Ltd\.?$", "Private Limited", canonical, flags=re.I)
    canonical = re.sub(r"\bLtd\.?$", "Limited", canonical, flags=re.I)
    rule = "company_legal_suffix" if canonical != source else "preserved_unknown"
    audit.record("companies", source, canonical, rule, 0.9 if canonical != source else 0.5)
    return canonical


_DATE_FORMATS = (("%Y-%m-%d", "%Y-%m-%d"), ("%Y-%m", "%Y-%m"), ("%Y", "%Y"), ("%b %Y", "%Y-%m"), ("%B %Y", "%Y-%m"))


def normalize_date(value: str | None, field: str, audit: NormalizationAudit) -> tuple[str | None, bool]:
    if not value:
        return None, False
    source = clean_text(value)
    if source.casefold() in {"present", "current", "now"}:
        audit.record(field, source, None, "current_date", 0.95)
        return None, True
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
    digits = re.sub(r"\D", "", source)
    if source.startswith("+") and 8 <= len(digits) <= 15:
        canonical = f"+{digits}"
        audit.record("phone", source, canonical, "e164_format", 0.9)
        return canonical
    audit.record("phone", source, source, "preserved_unknown", 0.5)
    return source
