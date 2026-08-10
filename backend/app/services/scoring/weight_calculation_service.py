from typing import Any

from app.schemas.scoring import ComponentScores, WeightedScores


class WeightCalculationService:
    @staticmethod
    def calculate(components: ComponentScores, config: Any) -> tuple[WeightedScores, float, float]:
        raw_weights = getattr(config, "weights", None)
        if isinstance(raw_weights, dict):
            weights = {
                "skills": float(raw_weights.get("skills", 40)),
                "experience": float(raw_weights.get("experience", 25)),
                "projects": float(raw_weights.get("projects", 15)),
                "education": float(raw_weights.get("education", 10)),
                "certifications": float(raw_weights.get("certifications", 5)),
                "languages": float(raw_weights.get("languages", 5)),
            }
        else:
            weights = {
                "skills": float(getattr(config, "skills_weight", 40)),
                "experience": float(getattr(config, "experience_weight", 25)),
                "projects": float(getattr(config, "projects_weight", 15)),
                "education": float(getattr(config, "education_weight", 10)),
                "certifications": float(getattr(config, "certifications_weight", 5)),
                "languages": float(getattr(config, "languages_weight", 5)),
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
