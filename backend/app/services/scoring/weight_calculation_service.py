from typing import Any

from app.schemas.scoring import ComponentScores, WeightedScores


class WeightCalculationService:
    @staticmethod
    def applicable_categories(job: Any, config: Any) -> set[str]:
        job_experience = getattr(job, "experience_requirements", None) or []
        return {
            name for name, applies in {
                "skills": bool((getattr(job, "skills", None) or []) or (getattr(config, "mandatory_skills", None) or [])),
                "experience": bool(
                    float(getattr(config, "min_experience_years", 0) or 0) > 0
                    or any((item.get("minimum_months") or 0) > 0 for item in job_experience)
                ),
                "projects": bool(getattr(job, "keywords", None) or []),
                "education": bool(
                    getattr(config, "required_degree", None)
                    or (getattr(job, "degree_requirements", None) or [])
                ),
                "certifications": bool(getattr(config, "required_certifications", None) or []),
                "languages": bool(getattr(config, "required_languages", None) or []),
            }.items() if applies
        }

    @staticmethod
    def calculate(
        components: ComponentScores,
        config: Any,
        applicable_categories: set[str] | None = None,
    ) -> tuple[WeightedScores, float, float]:
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
        applicable = set(weights) if applicable_categories is None else applicable_categories & set(weights)
        applicable_weight = sum(weights[name] for name in applicable)
        effective_weights = {
            name: (weights[name] / applicable_weight * 100 if name in applicable and applicable_weight else 0.0)
            for name in weights
        }
        weighted = {name: round(raw[name] * effective_weights[name] / 100, 2) for name in weights}
        raw_total = round(sum(raw[name] for name in applicable) / len(applicable), 2) if applicable else 0.0
        return WeightedScores(**weighted), raw_total, round(sum(weighted.values()), 2), {name: round(val, 2) for name, val in effective_weights.items()}

    @staticmethod
    def final_score(
        weighted_total: float,
        penalty_total: float,
        bonus_total: float,
        components: ComponentScores | None = None,
    ) -> float:
        """
        Calculates the final candidate score using a strict 50 + 50 hybrid model:
        1. Deterministic Skill Match (0-50 Marks):
           (matched required skills / total required skills) * 50
        2. AI JD Relevance & Evidence (0-50 Marks):
           LLM evaluation score of resume against actual JD context (0 to 50 marks).
        3. Final Score (0-100 Marks):
           Skill Match (0-50) + AI Relevance (0-50). Strictly sum of the two components.
        """
        if components is not None:
            skill_marks_50 = (components.skills.score / 100.0) * 50.0

            evidence_components = [
                components.experience.score,
                components.projects.score,
                components.education.score,
                components.certifications.score,
                components.languages.score,
            ]
            avg_evidence_score = sum(evidence_components) / len(evidence_components)
            evidence_marks_50 = (avg_evidence_score / 100.0) * 50.0

            # Pure 50 + 50 model: Final Score = Skill Match (0-50) + AI Relevance (0-50)
            return round(max(0.0, min(100.0, skill_marks_50 + evidence_marks_50)), 2)

        return round(max(0.0, min(100.0, weighted_total)), 2)

    @staticmethod
    def knockout(components: ComponentScores, config: Any) -> tuple[bool, str | None]:
        enabled = {rule.get("rule_type") for rule in (config.knockout_rules or []) if rule.get("enabled", True)}
        reasons = []
        if "MISSING_MANDATORY_SKILL" in enabled and components.skills.missing_items:
            mandatory = {value.strip().casefold() for value in config.mandatory_skills if value.strip()}
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
        if "DEGREE_MISMATCH" in enabled and components.education.score < 100:
            reasons.append("Required degree not met")
        return bool(reasons), "; ".join(reasons) or None
