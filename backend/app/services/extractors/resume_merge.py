from typing import Any


SCALARS = ("candidate_name", "email", "phone", "designation", "location")
SIMPLE_LISTS = ("skills", "certifications", "companies", "languages")
STRUCTURED_LISTS = ("education", "experience", "projects")


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _key(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _merge_strings(primary: list[str], recovery: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in [*primary, *recovery]:
        normalized = _key(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(value.strip())
    return result


def _identity(field: str, item: dict[str, Any]) -> str:
    if field == "projects":
        return _key(item.get("name"))
    if field == "education":
        return "|".join((_key(item.get("institution")), _key(item.get("degree")), _key(item.get("year"))))
    return "|".join((_key(item.get("company")), _key(item.get("title") or item.get("designation")), _key(item.get("start_date"))))


def _supplement(primary: dict[str, Any], recovery: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in recovery.items():
        if key in {"technologies", "responsibilities"}:
            merged[key] = _merge_strings(merged.get(key, []), value or [])
        elif not _present(merged.get(key)) and _present(value):
            merged[key] = value
    return merged


def _merge_structured(field: str, primary: list[dict[str, Any]], recovery: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [dict(item) for item in primary]
    positions = {_identity(field, item): index for index, item in enumerate(result) if _identity(field, item)}
    for item in recovery:
        identity = _identity(field, item)
        if identity and identity in positions:
            index = positions[identity]
            result[index] = _supplement(result[index], item)
        else:
            result.append(dict(item))
            if identity:
                positions[identity] = len(result) - 1
    return result


def merge_resume_extractions(deterministic: dict[str, Any], ai: dict[str, Any] | None) -> dict[str, Any]:
    """Preserve deterministic facts and use AI only for recovery/supplementation."""
    if not ai:
        return deterministic
    merged = dict(deterministic)
    for field in SCALARS:
        if not _present(merged.get(field)) and _present(ai.get(field)):
            merged[field] = ai[field]
    for field in SIMPLE_LISTS:
        merged[field] = _merge_strings(merged.get(field, []), ai.get(field, []))
    for field in STRUCTURED_LISTS:
        merged[field] = _merge_structured(field, merged.get(field, []), ai.get(field, []))
    metadata = dict(merged.get("raw_metadata", {}))
    metadata["ai_recovery"] = "merged"
    merged["raw_metadata"] = metadata
    return merged
