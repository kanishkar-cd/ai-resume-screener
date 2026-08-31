import re
from typing import Any
from app.schemas.scoring import AdjustmentItem, ComponentScores
from app.services.pipeline.canonical_dictionaries import SKILL_ALIASES, SKILL_CATEGORIES, CATEGORY_REQUIREMENT_ALIASES
from app.services.scoring.component_scoring_service import ComponentScoringService


class BonusService:
    CAP = 15.0

    @classmethod
    def calculate(
        cls,
        resume: Any,
        job: Any,
        config: Any,
        components: ComponentScores,
        match_verdicts: list[Any] | None = None,
        projects: list[dict[str, Any]] | None = None,
    ) -> tuple[float, list[AdjustmentItem]]:
        items: list[AdjustmentItem] = []

        # 1. Pool candidate terms from skills, certs, projects, experience, and validated match verdicts
        candidate_terms: list[str] = [
            *(getattr(resume, "skills", None) or []),
            *(getattr(resume, "certifications", None) or []),
            *[t for p in (projects or getattr(resume, "projects", []) or []) for t in (p.get("technologies") or [])],
            *[p.get("name") for p in (projects or getattr(resume, "projects", []) or []) if p.get("name")],
            *[t for exp in (getattr(resume, "experience", None) or []) for t in (exp.get("technologies") or [])],
        ]

        # Extract text blobs from experience and projects for phrase matching
        evidence_text_parts: list[str] = list(candidate_terms)
        for exp in (getattr(resume, "experience", None) or []):
            if exp.get("description"):
                evidence_text_parts.append(exp["description"])
            for r in (exp.get("responsibilities") or []):
                evidence_text_parts.append(r)
        for p in (projects or getattr(resume, "projects", []) or []):
            if p.get("description"):
                evidence_text_parts.append(p["description"])

        combined_evidence_text = " ".join(evidence_text_parts).casefold()
        candidate_keys = {val.strip().casefold() for val in candidate_terms if val and str(val).strip()}

        # Also collect matched requirement IDs from match_verdicts
        matched_verdict_ids = {
            getattr(v, "requirement_id", None)
            for v in (match_verdicts or [])
            if str(getattr(v, "status", "")).upper() in {"MATCHED", "MATCHSTATUS.MATCHED"}
        }

        preferred_skills = getattr(config, "preferred_skills", None) or getattr(job, "preferred_skills", None) or []
        preferred_by_key: dict[str, str] = {}
        for value in preferred_skills:
            stripped = value.strip()
            if stripped:
                preferred_by_key.setdefault(stripped.casefold(), stripped)

        matched_preferred: list[str] = []
        for key, display_name in preferred_by_key.items():
            matched = False

            # Check direct match or canonical aliases
            if key in candidate_keys:
                matched = True
            else:
                canonical = SKILL_ALIASES.get(key)
                if canonical and canonical.casefold() in candidate_keys:
                    matched = True
                else:
                    if any(SKILL_ALIASES.get(ck) == display_name or SKILL_ALIASES.get(ck) == key.upper() for ck in candidate_keys):
                        matched = True

            # Check word boundary regex in combined evidence text (e.g. "Docker" in experience text)
            if not matched and len(key) >= 3:
                escaped = re.escape(key)
                if re.search(rf"(?:\b|_){escaped}(?:\b|_)", combined_evidence_text, re.IGNORECASE):
                    matched = True

            # Check if requirement was validated by match_verdicts
            if not matched and match_verdicts:
                if any(
                    display_name.casefold() in str(getattr(v, "reasoning", "")).casefold() or
                    key in str(getattr(v, "requirement_id", "")).casefold()
                    for v in match_verdicts
                    if getattr(v, "requirement_id", None) in matched_verdict_ids
                ):
                    matched = True

            if matched:
                matched_preferred.append(display_name)

        if matched_preferred:
            items.append(
                AdjustmentItem(
                    rule_name="PREFERRED_SKILLS",
                    delta_points=2.0 * len(matched_preferred),
                    description=f"Matched preferred skills: {', '.join(matched_preferred)}",
                )
            )

        candidate_months = sum(item.get("duration_months") or 0 for item in (getattr(resume, "experience", None) or []))
        min_exp_years = float(getattr(config, "min_experience_years", 0) or 0)
        required_months = max([item.get("minimum_months") or 0 for item in (getattr(job, "experience_requirements", None) or [])] or [round(min_exp_years * 12)])
        if candidate_months >= required_months + 36:
            items.append(AdjustmentItem(rule_name="OVER_QUALIFICATION", delta_points=5.0, description="At least three additional years of experience."))

        total = min(cls.CAP, sum(item.delta_points for item in items))
        if sum(item.delta_points for item in items) > cls.CAP:
            items.append(AdjustmentItem(rule_name="BONUS_CAP", delta_points=0, description="Total bonuses capped at 15 points."))
        return round(total, 2), items
