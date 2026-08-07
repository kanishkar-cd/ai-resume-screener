from typing import Any

from app.schemas.scoring import ComponentScores, WeightedScores


class WeightCalculationService:
    @staticmethod
    def calculate(components: ComponentScores, config: Any) -> tuple[WeightedScores, float, float]:
        weights = {
            "skills": float(config.skills_weight), "experience": float(config.experience_weight),
            "projects": float(config.projects_weight), "education": float(config.education_weight),
            "certifications": float(config.certifications_weight), "languages": float(config.languages_weight),
        }
        raw = {name: getattr(components, name).score for name in weights}
        weighted = {name: round(raw[name] * weights[name] / 100, 2) for name in weights}
        return WeightedScores(**weighted), round(sum(raw.values()) / len(raw), 2), round(sum(weighted.values()), 2)

    @staticmethod
    def knockout(components: ComponentScores, config: Any) -> tuple[bool, str | None]:
        enabled = {rule.get("rule_type") for rule in (config.knockout_rules or []) if rule.get("enabled", True)}
        reasons = []
        if "MISSING_MANDATORY_SKILL" in enabled and components.skills.missing_items:
            mandatory = {value.casefold() for value in config.mandatory_skills}
            missing = [value for value in components.skills.missing_items if value.casefold() in mandatory]
            if missing: reasons.append(f"Missing mandatory skills: {', '.join(missing)}")
        if "INSUFFICIENT_EXPERIENCE" in enabled and components.experience.missing_items:
            reasons.append("Insufficient experience")
        if "DEGREE_MISMATCH" in enabled and components.education.score < 100:
            reasons.append("Required degree not met")
        return bool(reasons), "; ".join(reasons) or None
