from app.services.pipeline.canonical_dictionaries import DEGREE_ALIASES, SKILL_ALIASES
from app.services.pipeline.normalization_rules import (
    NormalizationAudit, canonicalize, duration_between, normalize_phone,
    parse_experience_requirement, stable_unique,
)


def test_aliases_are_canonical_and_deterministic() -> None:
    audit = NormalizationAudit()
    assert [canonicalize(value, SKILL_ALIASES, "skills", audit) for value in ("python", "PYTHON", "Py")] == ["Python"] * 3
    assert canonicalize("B.E.", DEGREE_ALIASES, "degree", audit) == "Bachelor of Engineering"
    assert stable_unique(["Python", "python", "PostgreSQL"]) == ["Python", "PostgreSQL"]


def test_duration_phone_and_unknown_rules() -> None:
    audit = NormalizationAudit()
    assert parse_experience_requirement("3 yrs", audit) == {"minimum_months": 36, "maximum_months": 36, "display_value": "3 years"}
    assert parse_experience_requirement("3-5 years", audit)["maximum_months"] == 60
    assert parse_experience_requirement("3+ years", audit)["maximum_months"] is None
    assert normalize_phone("+91-98765-43210", audit) == "+919876543210"
    assert normalize_phone("9876543210", audit) == "9876543210"
    assert duration_between("2021-01", "2023-12", False) == 36
    assert any("phone" in warning for warning in audit.metadata()["warnings"])
