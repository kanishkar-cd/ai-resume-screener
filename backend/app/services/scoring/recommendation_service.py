from typing import Any

from app.schemas.scoring import RecommendationLevel, ComponentScores


SHORTLIST_COMPONENT_THRESHOLD = 50.0


class RecommendationService:
    @staticmethod
    def evaluate(
        components: Any | None,
        is_knocked_out: bool = False,
        knockout_reason: str | None = None,
        effective_weights: dict[str, float] | None = None,
        applicable_categories: set[str] | None = None,
        active_components: set[str] | None = None,
    ) -> tuple[RecommendationLevel, str]:
        """
        Evaluates candidate recommendation based on component-level evidence rules.
        Does NOT calculate or depend on an Overall Score.
        Zero-weight / inactive components MUST NOT count as additional evidence for AUTO-SHORTLIST.
        """
        if is_knocked_out:
            reason = f"REJECT because a mandatory requirement was not satisfied: {knockout_reason or 'unspecified mandatory requirement'}."
            return RecommendationLevel.REJECT, reason

        if components is None:
            return RecommendationLevel.REJECT, "REJECT because no component scores were available."

        # Helper to check if a component is active (applicable for the current JD with effective weight > 0)
        def is_active(cat_key: str, comp_obj: Any = None) -> bool:
            if active_components is not None:
                return cat_key in active_components or (cat_key == "required_skills" and "skills" in active_components)

            if applicable_categories is not None:
                return cat_key in applicable_categories or (cat_key == "required_skills" and "skills" in applicable_categories)

            if effective_weights is not None:
                return float(effective_weights.get(cat_key, 0.0) or 0.0) > 0.0

            if comp_obj is not None:
                obj_w = getattr(comp_obj, "weight", None)
                if obj_w is not None:
                    return float(obj_w) > 0.0

            # Default fallbacks based on base COMPONENT_WEIGHTS:
            # required_skills (30%), responsibilities (25%), projects (25%) are active core components by default.
            if cat_key in ("required_skills", "skills", "responsibilities", "projects"):
                return True
            # preferred_skills (15%) and certifications (5%) base weights are > 0 by default.
            if cat_key == "preferred_skills":
                return True
            if cat_key == "certifications":
                return True
            # experience (0%) and education (0%) base weights are 0.0%, so inactive by default.
            return False

        # Extract core component objects and scores
        skills_obj = getattr(components, "skills", None)
        skills_score = float(getattr(skills_obj, "score", 0.0) or 0.0)

        resp_obj = getattr(components, "responsibilities", None)
        resp_score = float(getattr(resp_obj, "score", 0.0) or 0.0) if resp_obj is not None else 0.0

        proj_obj = getattr(components, "projects", None)
        proj_score = float(getattr(proj_obj, "score", 0.0) or 0.0)

        # Extract supporting component objects and scores
        pref_obj = getattr(components, "preferred_skills", None)
        pref_score = float(getattr(pref_obj, "score", 0.0) or 0.0) if pref_obj is not None else 0.0

        cert_obj = getattr(components, "certifications", None)
        cert_score = float(getattr(cert_obj, "score", 0.0) or 0.0)

        edu_obj = getattr(components, "education", None)
        edu_score = float(getattr(edu_obj, "score", 0.0) or 0.0)

        core_scores = {
            "Required Skills": skills_score,
            "Responsibilities": resp_score,
            "Projects": proj_score,
        }

        # Check core threshold (>= 50.0%) for active core components
        triggered_core_names = [
            name for name, score in core_scores.items()
            if score >= SHORTLIST_COMPONENT_THRESHOLD
        ]

        # Check additional evidence from OTHER ACTIVE components
        additional_evidence = []
        if "Required Skills" not in triggered_core_names and skills_score > 0 and is_active("required_skills", skills_obj):
            additional_evidence.append(f"Required Skills ({skills_score:.0f}%)")

        if "Responsibilities" not in triggered_core_names and resp_score > 0 and is_active("responsibilities", resp_obj):
            additional_evidence.append(f"Responsibilities ({resp_score:.0f}%)")

        if "Projects" not in triggered_core_names and proj_score > 0 and is_active("projects", proj_obj):
            additional_evidence.append(f"Projects ({proj_score:.0f}%)")

        if pref_score > 0 and is_active("preferred_skills", pref_obj):
            additional_evidence.append(f"Preferred Skills ({pref_score:.0f}%)")

        if cert_score > 0 and is_active("certifications", cert_obj):
            additional_evidence.append(f"Certifications ({cert_score:.0f}%)")

        if edu_score > 0 and is_active("education", edu_obj):
            additional_evidence.append(f"Education ({edu_score:.0f}%)")

        # 1. AUTO-SHORTLIST Rule:
        # NO knockout AND at least ONE CORE >= 50% AND at least ONE OTHER ACTIVE component has meaningful evidence.
        if triggered_core_names and additional_evidence:
            core_desc = ", ".join(f"{name} ({core_scores[name]:.0f}%)" for name in triggered_core_names)
            add_desc = ", ".join(additional_evidence)
            reason = (
                f"SHORTLIST because {core_desc} coverage reached or exceeded the {SHORTLIST_COMPONENT_THRESHOLD:.0f}% "
                f"component threshold, with additional matching evidence in {add_desc}."
            )
            return RecommendationLevel.SHORTLIST, reason

        # 2. REVIEW Rule:
        # If no AUTO-SHORTLIST, check if candidate has meaningful partial matching across active core components
        has_meaningful_core_matching = any(
            score >= 25.0 and is_active(cat_key)
            for cat_key, score in [("required_skills", skills_score), ("responsibilities", resp_score), ("projects", proj_score)]
        ) or (
            skills_score >= 20.0 and (resp_score >= 20.0 or proj_score >= 20.0)
        )
        if has_meaningful_core_matching:
            core_parts = [f"{name} ({score:.0f}%)" for name, score in core_scores.items() if score > 0]
            core_desc = ", ".join(core_parts) or "core components"
            reason = (
                f"REVIEW because no core component reached the {SHORTLIST_COMPONENT_THRESHOLD:.0f}% shortlist threshold, "
                f"but meaningful partial matching exists across {core_desc}."
            )
            return RecommendationLevel.REVIEW, reason

        # 3. REJECT Rule:
        reason = f"REJECT because no core component reached the {SHORTLIST_COMPONENT_THRESHOLD:.0f}% shortlist threshold and insufficient matching evidence was found."
        return RecommendationLevel.REJECT, reason

    @staticmethod
    def recommend(
        final_score: float = 0.0,
        passing_score: float = 70.0,
        is_knocked_out: bool = False,
        use_absolute_thresholds: bool = False,
        components: Any = None,
        knockout_reason: str | None = None,
        effective_weights: dict[str, float] | None = None,
        applicable_categories: set[str] | None = None,
        active_components: set[str] | None = None,
    ) -> RecommendationLevel:
        level, _ = RecommendationService.evaluate(
            components=components,
            is_knocked_out=is_knocked_out,
            knockout_reason=knockout_reason,
            effective_weights=effective_weights,
            applicable_categories=applicable_categories,
            active_components=active_components,
        )
        return level


