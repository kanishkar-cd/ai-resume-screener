from typing import Any

from app.schemas.scoring import ComponentScores, WeightedScores


COMPONENT_WEIGHTS: dict[str, float] = {
    "required_skills": 30.0,
    "responsibilities": 25.0,
    "projects": 25.0,
    "preferred_skills": 15.0,
    "experience": 0.0,
    "certifications": 5.0,
    "education": 0.0,
}


class WeightCalculationService:
    @staticmethod
    def applicable_categories(job: Any, config: Any = None) -> set[str]:
        job_experience = getattr(job, "experience_requirements", None) or []
        mandatory_skills = getattr(config, "mandatory_skills", None) or []
        min_exp = float(getattr(config, "min_experience_years", 0) or 0)
        req_deg = getattr(config, "required_degree", None) or getattr(job, "required_degree", None)
        req_certs = getattr(config, "required_certifications", None) or []
        req_langs = getattr(config, "required_languages", None) or []

        has_skills = bool((getattr(job, "skills", None) or []) or (getattr(job, "required_skills", None) or []) or mandatory_skills)
        has_resp = bool(getattr(job, "responsibilities", None) or [])
        has_proj = bool(
            (getattr(job, "project_requirements", None) or [])
            or (getattr(config, "required_projects", None) if config else None)
            or (getattr(job, "keywords", None) or [])
            or (config is not None and bool(getattr(job, "responsibilities", None) or []))
        )
        has_pref = bool(getattr(job, "preferred_skills", None) or [])
        has_exp = False  # Experience weight removed (0% direct weighted contribution)
        has_edu = bool(
            req_deg
            or (getattr(job, "required_degree", None))
            or (getattr(job, "degree_requirements", None) or [])
            or (getattr(job, "qualifications", None) or [])
            or (getattr(config, "required_degree", None) if config else None)
        )
        has_certs = bool(req_certs or (getattr(job, "certifications", None) or []))

        return {
            name for name, applies in {
                "required_skills": has_skills,
                "skills": has_skills,
                "responsibilities": has_resp,
                "projects": has_proj,
                "preferred_skills": has_pref,
                "experience": has_exp,
                "education": has_edu,
                "certifications": has_certs,
                "languages": bool(req_langs),
            }.items() if applies
        }

    @staticmethod
    def calculate(
        components: ComponentScores,
        config: Any = None,
        applicable_categories: set[str] | None = None,
    ) -> tuple[WeightedScores, float, float, dict[str, float]]:
        comp_scores = {
            "required_skills": components.skills.score,
            "responsibilities": (components.responsibilities.score if getattr(components, "responsibilities", None) is not None else components.experience.score),
            "projects": components.projects.score,
            "preferred_skills": (components.preferred_skills.score if getattr(components, "preferred_skills", None) is not None else 100.0),
            "experience": components.experience.score,
            "certifications": components.certifications.score,
            "education": components.education.score,
        }

        if applicable_categories is not None:
            applicable = set()
            for c in applicable_categories:
                if c == "skills":
                    applicable.add("required_skills")
                elif c in COMPONENT_WEIGHTS:
                    applicable.add(c)
        else:
            applicable = set(c for c in COMPONENT_WEIGHTS.keys() if c != "experience")

        total_applicable_weight = sum(COMPONENT_WEIGHTS[c] for c in applicable)
        effective_weights = {
            c: ((COMPONENT_WEIGHTS[c] / total_applicable_weight * 100.0) if c in applicable and total_applicable_weight else 0.0)
            for c in COMPONENT_WEIGHTS
        }

        weighted_values = {
            c: round(comp_scores[c] * effective_weights[c] / 100.0, 2)
            for c in COMPONENT_WEIGHTS
        }

        raw_total = round(min(100.0, max(0.0, sum(comp_scores[c] for c in applicable) / len(applicable))), 2) if applicable else 0.0
        weighted_total = round(min(100.0, max(0.0, sum(weighted_values.values()))), 2)

        weighted_schema = WeightedScores(
            skills=weighted_values["required_skills"],
            responsibilities=weighted_values["responsibilities"],
            projects=weighted_values["projects"],
            preferred_skills=weighted_values["preferred_skills"],
            experience=0.0,
            certifications=weighted_values["certifications"],
            education=weighted_values["education"],
            languages=0.0,
        )

        return weighted_schema, raw_total, weighted_total, {name: round(val, 2) for name, val in effective_weights.items()}

    @staticmethod
    def final_score(
        weighted_total: float = 0.0,
        penalty_total: float = 0.0,
        bonus_total: float = 0.0,
        components: ComponentScores | None = None,
        applicable_categories: set[str] | None = None,
    ) -> float:
        """
        Overall score aggregation removed per system specification.
        Returns 0.0 while preserving component weights and component scoring.
        """
        return 0.0

    @staticmethod
    def knockout(components: ComponentScores, config: Any) -> tuple[bool, str | None]:
        knockout_rules = getattr(config, "knockout_rules", None) or []
        enabled = {rule.get("rule_type") for rule in knockout_rules if rule.get("enabled", True)}
        reasons = []
        if "MISSING_MANDATORY_SKILL" in enabled and components.skills.missing_items:
            mandatory_skills = getattr(config, "mandatory_skills", None) or []
            mandatory = {value.strip().casefold() for value in mandatory_skills if value.strip()}
            missing = []
            seen: set[str] = set()
            for value in components.skills.missing_items:
                key = value.strip().casefold()
                if key in mandatory and key not in seen:
                    missing.append(value)
                    seen.add(key)
            if missing: reasons.append(f"Missing mandatory skills: {', '.join(missing)}")
        if "INSUFFICIENT_EXPERIENCE" in enabled and components.experience.missing_items:
            reasons.append("Insufficient experience")
        return bool(reasons), "; ".join(reasons) or None
