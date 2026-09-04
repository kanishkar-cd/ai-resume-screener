from typing import Any

from app.schemas.scoring import ComponentScores, WeightedScores


# Authoritative default business weights summing to exactly 100.0%
DEFAULT_WEIGHTS: dict[str, float] = {
    "required_skills": 45.0,
    "responsibilities": 40.0,
    "preferred_skills": 15.0,
    "certifications": 0.0,
    "experience": 0.0,
    "education": 0.0,
    "languages": 0.0,
    "projects": 0.0,
}

COMPONENT_WEIGHTS: dict[str, float] = DEFAULT_WEIGHTS


def validate_weights(weights: dict[str, float]) -> None:
    """Validate that the configured categories sum to exactly 100.0%."""
    total = sum(float(v) for v in weights.values())
    if abs(total - 100.0) > 1e-4:
        raise ValueError(
            f"Configured weights must sum to 100.0%, got {total:.2f}% (weights={weights})"
        )


# Validate default weights at module import time
validate_weights(DEFAULT_WEIGHTS)


class WeightCalculationService:
    # Configurable required-skill safeguard parameters
    SAFEGUARD_ENABLED: bool = True
    SAFEGUARD_CRITICAL_SKILL_THRESHOLD: float = 50.0  # Threshold under which required skill protection triggers
    SAFEGUARD_ZERO_SKILLS_MAX_SCORE: float = 35.0    # Hard ceiling if candidate matches 0 required skills

    @staticmethod
    def applicable_categories(job: Any, config: Any = None) -> set[str]:
        # Required criteria that form Core requirements
        mandatory_skills = getattr(config, "mandatory_skills", None) or []

        has_skills = bool((getattr(job, "skills", None) or []) or (getattr(job, "required_skills", None) or []) or mandatory_skills)
        has_resp = bool(getattr(job, "responsibilities", None) or [])
        has_pref = bool(getattr(job, "preferred_skills", None) or [])

        return {
            name for name, applies in {
                "required_skills": has_skills,
                "skills": has_skills,
                "responsibilities": has_resp,
                "preferred_skills": has_pref,
                "projects": False,
                "experience": False,
                "education": False,
                "certifications": False,
                "languages": False,
            }.items() if applies
        }

    @staticmethod
    def calculate(
        components: ComponentScores,
        config: Any = None,
        applicable_categories: set[str] | None = None,
    ) -> tuple[WeightedScores, float, float, dict[str, float]]:
        """
        Calculate weighted score using authoritative business weights:
        - Required Skills: 45%
        - Responsibilities: 40%
        - Preferred Skills: 15%
        All other categories: 0% (serve as evidence only).
        Total: 100%

        When a category is genuinely absent from the JD, its configured weight is
        proportionally redistributed across the remaining active categories according
        to their original configured weights.

        If a category exists in the JD but candidate scores zero, that category remains
        active at its configured weight (never redistributed).
        """
        weights = dict(DEFAULT_WEIGHTS)
        cfg_weights = getattr(config, "weights", None)
        if cfg_weights is not None:
            if hasattr(cfg_weights, "model_dump"):
                cfg_weights = cfg_weights.model_dump()
            if isinstance(cfg_weights, dict):
                mapped = {}
                for k in ("required_skills", "responsibilities", "preferred_skills"):
                    alt_k = "skills" if k == "required_skills" else k
                    if k in cfg_weights:
                        mapped[k] = float(cfg_weights[k])
                    elif alt_k in cfg_weights:
                        mapped[k] = float(cfg_weights[alt_k])
                    else:
                        mapped[k] = weights[k]
                for k in ("projects", "experience", "education", "certifications", "languages"):
                    mapped[k] = 0.0
                validate_weights(mapped)
                weights = mapped
        elif any(hasattr(config, attr) for attr in ("skills_weight", "required_skills_weight", "responsibilities_weight", "preferred_skills_weight")):
            mapped = dict(DEFAULT_WEIGHTS)
            if hasattr(config, "required_skills_weight"):
                mapped["required_skills"] = float(config.required_skills_weight)
            elif hasattr(config, "skills_weight"):
                mapped["required_skills"] = float(config.skills_weight)
            if hasattr(config, "responsibilities_weight"):
                mapped["responsibilities"] = float(config.responsibilities_weight)
            if hasattr(config, "preferred_skills_weight"):
                mapped["preferred_skills"] = float(config.preferred_skills_weight)
            for k in ("projects", "experience", "education", "certifications", "languages"):
                mapped[k] = 0.0
            total_cfg = sum(mapped.values())
            if abs(total_cfg - 100.0) <= 1e-4:
                weights = mapped

        core_categories = ("required_skills", "responsibilities", "projects", "preferred_skills", "experience", "certifications", "education", "languages")

        def _is_active_in_jd(comp_detail: Any, cat_name: str) -> bool:
            if applicable_categories is not None:
                if cat_name == "required_skills":
                    return "required_skills" in applicable_categories or "skills" in applicable_categories
                return cat_name in applicable_categories
            if comp_detail is None:
                return False
            # If not in the 3 scored categories, it is not an active scoring category
            if cat_name not in ("required_skills", "responsibilities", "preferred_skills"):
                return False
            explanation = str(getattr(comp_detail, "explanation", "") or "").casefold()
            is_na = "(n/a)" in explanation or ("no " in explanation and "configured" in explanation)
            has_items = bool(getattr(comp_detail, "matched_items", None) or getattr(comp_detail, "missing_items", None))
            if is_na and not has_items:
                return False
            return True

        active_categories = {
            c for c in core_categories
            if _is_active_in_jd(
                components.skills if c == "required_skills" else getattr(components, c, None),
                c
            )
        }

        active_weight_total = sum(weights.get(c, 0.0) for c in active_categories)

        effective_weights: dict[str, float] = {}
        if active_weight_total > 0:
            for c in core_categories:
                if c in active_categories:
                    effective_weights[c] = round((weights.get(c, 0.0) / active_weight_total) * 100.0, 4)
                else:
                    effective_weights[c] = 0.0

            # Ensure the active effective weights sum to exactly 100.0%
            active_sum = sum(effective_weights[c] for c in active_categories)
            diff = 100.0 - active_sum
            if abs(diff) > 1e-5:
                active_list = [c for c in core_categories if c in active_categories and effective_weights[c] > 0]
                if active_list:
                    last_cat = active_list[-1]
                    effective_weights[last_cat] = round(effective_weights[last_cat] + diff, 4)
        else:
            for c in core_categories:
                effective_weights[c] = 0.0

        def _get_comp_score(comp_detail: Any, cat_name: str) -> float:
            if cat_name not in active_categories or comp_detail is None:
                return 0.0
            raw_score = getattr(comp_detail, "score", 0.0)
            return float(raw_score) if raw_score is not None else 0.0

        comp_scores = {
            "required_skills": _get_comp_score(components.skills, "required_skills"),
            "preferred_skills": _get_comp_score(getattr(components, "preferred_skills", None), "preferred_skills"),
            "responsibilities": _get_comp_score(getattr(components, "responsibilities", None), "responsibilities"),
            "projects": _get_comp_score(getattr(components, "projects", None), "projects"),
            "experience": _get_comp_score(getattr(components, "experience", None), "experience"),
            "certifications": _get_comp_score(getattr(components, "certifications", None), "certifications"),
            "education": _get_comp_score(getattr(components, "education", None), "education"),
            "languages": _get_comp_score(getattr(components, "languages", None), "languages"),
        }

        weighted_values = {
            c: round(comp_scores[c] * (effective_weights.get(c, 0.0) / 100.0), 2)
            for c in core_categories
        }

        # Calculate final weighted total using unrounded values to prevent rounding drift
        raw_weighted_total = sum(comp_scores[c] * (effective_weights.get(c, 0.0) / 100.0) for c in active_categories)

        # ── REQUIRED SKILL PROTECTION SAFEGUARD ─────────────────────────────
        # If required skills are active in the JD, a candidate with critical missing required skills
        # must not receive an unrealistically high match score purely from responsibilities or preferred skills.
        is_req_active = "required_skills" in active_categories
        req_score = comp_scores.get("required_skills", 0.0)

        if WeightCalculationService.SAFEGUARD_ENABLED and is_req_active:
            if req_score <= 0.0:
                # 0% required skills matched -> cap score at safe critical ceiling
                guarded_total = min(raw_weighted_total, WeightCalculationService.SAFEGUARD_ZERO_SKILLS_MAX_SCORE)
            elif req_score < WeightCalculationService.SAFEGUARD_CRITICAL_SKILL_THRESHOLD:
                # Under 50% required skills matched -> cap proportional to required skill coverage
                score_cap = req_score + (100.0 - req_score) * 0.40
                guarded_total = min(raw_weighted_total, score_cap)
            else:
                guarded_total = raw_weighted_total
        else:
            guarded_total = raw_weighted_total

        weighted_total = round(min(100.0, max(0.0, guarded_total)), 2)

        raw_total = round(
            min(100.0, max(0.0,
                (sum(comp_scores[c] for c in active_categories) / len(active_categories)) if active_categories else 0.0
            )),
            2
        )

        weighted_schema = WeightedScores(
            skills=weighted_values["required_skills"],
            preferred_skills=weighted_values["preferred_skills"],
            responsibilities=weighted_values["responsibilities"],
            projects=weighted_values["projects"],
            experience=weighted_values["experience"],
            certifications=weighted_values["certifications"],
            education=weighted_values["education"],
            languages=weighted_values["languages"],
        )

        return weighted_schema, raw_total, weighted_total, effective_weights

    @staticmethod
    def final_score(
        weighted_total: float = 0.0,
        penalty_total: float = 0.0,
        bonus_total: float = 0.0,
        components: ComponentScores | None = None,
        applicable_categories: set[str] | None = None,
        config: Any = None,
    ) -> float:
        """
        Calculates final score from the active weighted model.
        When categories are absent, their weight is proportionally redistributed.
        Preferred skills contribute via their effective weight and are not added as an external bonus.
        """
        if components is not None:
            _, _, calc_total, _ = WeightCalculationService.calculate(
                components, config=config, applicable_categories=applicable_categories
            )
            base_score = calc_total
        else:
            base_score = weighted_total + bonus_total

        return round(min(100.0, max(0.0, base_score)), 2)

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
