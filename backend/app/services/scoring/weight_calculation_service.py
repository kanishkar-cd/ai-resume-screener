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
        # Required criteria that form Core requirements
        mandatory_skills = getattr(config, "mandatory_skills", None) or []
        req_deg = getattr(config, "required_degree", None) or getattr(job, "required_degree", None)
        req_certs = getattr(config, "required_certifications", None) or []
        req_langs = getattr(config, "required_languages", None) or []

        has_skills = bool((getattr(job, "skills", None) or []) or (getattr(job, "required_skills", None) or []) or mandatory_skills)
        has_resp = bool(getattr(job, "responsibilities", None) or [])
        has_proj = bool(
            (getattr(job, "project_requirements", None) or [])
            or (getattr(config, "required_projects", None) if config else None)
        )
        has_pref = bool(getattr(job, "preferred_skills", None) or [])
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
                "experience": False,
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
        """
        Calculate Core Requirements Score.
        All required items (skills, responsibilities, projects, required qualifications)
        are treated as Core requirements.
        Preferred requirements are supporting/bonus only (0% direct core weight; non-deductible).
        """
        comp_scores = {
            "required_skills": components.skills.score,
            "responsibilities": (components.responsibilities.score if getattr(components, "responsibilities", None) is not None else components.experience.score),
            "projects": components.projects.score,
            "preferred_skills": (components.preferred_skills.score if getattr(components, "preferred_skills", None) is not None else 100.0),
            "experience": components.experience.score,
            "certifications": components.certifications.score,
            "education": components.education.score,
        }

        def _get_item_count(comp_detail: Any) -> int:
            if comp_detail is None:
                return 0
            matched = len(getattr(comp_detail, "matched_items", []) or [])
            missing = len(getattr(comp_detail, "missing_items", []) or [])
            return matched + missing

        core_categories = ["required_skills", "responsibilities", "projects", "certifications", "education"]
        if applicable_categories is not None:
            active_core = [
                c for c in core_categories
                if c in applicable_categories or (c == "required_skills" and "skills" in applicable_categories)
            ]
        else:
            active_core = ["required_skills", "responsibilities", "projects"]

        if not active_core:
            active_core = ["required_skills", "responsibilities"]

        counts = {
            "required_skills": _get_item_count(components.skills),
            "responsibilities": _get_item_count(getattr(components, "responsibilities", None)),
            "projects": _get_item_count(components.projects),
            "certifications": _get_item_count(components.certifications),
            "education": _get_item_count(components.education),
        }

        total_core_items = sum(counts[c] for c in active_core)

        effective_weights: dict[str, float] = {}
        if total_core_items > 0:
            for c in core_categories:
                if c in active_core and counts[c] > 0:
                    effective_weights[c] = round(counts[c] / total_core_items * 100.0, 2)
                else:
                    effective_weights[c] = 0.0
        else:
            eq_w = round(100.0 / len(active_core), 2) if active_core else 0.0
            for c in core_categories:
                effective_weights[c] = eq_w if c in active_core else 0.0

        effective_weights["preferred_skills"] = 0.0
        effective_weights["experience"] = 0.0

        # Adjust any rounding discrepancy so active core sum is exactly 100.0
        active_sum = sum(effective_weights.get(c, 0.0) for c in active_core)
        if active_sum > 0 and abs(active_sum - 100.0) > 0.001:
            first_active = [c for c in active_core if effective_weights.get(c, 0.0) > 0]
            if first_active:
                lead = first_active[0]
                effective_weights[lead] = round(effective_weights[lead] + (100.0 - active_sum), 2)

        weighted_values = {
            c: round(comp_scores[c] * effective_weights.get(c, 0.0) / 100.0, 2)
            for c in ["required_skills", "responsibilities", "projects", "preferred_skills", "experience", "certifications", "education"]
        }

        # Calculate unrounded sum to avoid intermediate rounding drift
        core_base_score = round(min(100.0, max(0.0, sum(comp_scores[c] * effective_weights.get(c, 0.0) / 100.0 for c in active_core))), 2) if active_core else 0.0
        raw_total = round(min(100.0, max(0.0, sum(comp_scores[c] for c in active_core) / len(active_core))), 2) if active_core else 0.0

        weighted_schema = WeightedScores(
            skills=weighted_values["required_skills"],
            responsibilities=weighted_values["responsibilities"],
            projects=weighted_values["projects"],
            preferred_skills=0.0,
            experience=0.0,
            certifications=weighted_values["certifications"],
            education=weighted_values["education"],
            languages=0.0,
        )

        return weighted_schema, raw_total, core_base_score, {name: round(val, 2) for name, val in effective_weights.items()}

    @staticmethod
    def final_score(
        weighted_total: float = 0.0,
        penalty_total: float = 0.0,
        bonus_total: float = 0.0,
        components: ComponentScores | None = None,
        applicable_categories: set[str] | None = None,
    ) -> float:
        """
        Calculates final score from Core requirements total + Bonus total.
        Penalties are 0.0 (unearned points only, never penalty deductions).
        """
        if components is not None:
            _, _, calc_core, _ = WeightCalculationService.calculate(
                components, applicable_categories=applicable_categories
            )
            base_score = calc_core
        else:
            base_score = weighted_total

        return round(min(100.0, max(0.0, base_score + bonus_total)), 2)



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
