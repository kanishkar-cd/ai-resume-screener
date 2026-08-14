from typing import Any
from app.schemas.scoring import AdjustmentItem, ComponentScores
from app.services.scoring.component_scoring_service import ComponentScoringService


class BonusService:
    CAP = 15.0

    @classmethod
    def calculate(cls, resume: Any, job: Any, config: Any, components: ComponentScores) -> tuple[float, list[AdjustmentItem]]:
        items: list[AdjustmentItem] = []
        candidate = {value.strip().casefold() for value in resume.skills if value.strip()}
        preferred_by_key: dict[str, str] = {}
        preferred_skills = getattr(config, "preferred_skills", None) or getattr(job, "preferred_skills", None) or []
        for value in preferred_skills:
            stripped = value.strip()
            if stripped:
                preferred_by_key.setdefault(stripped.casefold(), stripped)
        preferred = [value for key, value in preferred_by_key.items() if key in candidate]
        if preferred:
            items.append(AdjustmentItem(rule_name="PREFERRED_SKILLS", delta_points=2.0 * len(preferred), description=f"Matched preferred skills: {', '.join(preferred)}"))
        candidate_months = sum(item.get("duration_months") or 0 for item in resume.experience)
        min_exp_years = float(getattr(config, "min_experience_years", 0) or 0)
        required_months = max([item.get("minimum_months") or 0 for item in job.experience_requirements] or [round(min_exp_years * 12)])
        candidate_rank = max((ComponentScoringService.degree_rank(item.get("degree")) for item in resume.education), default=0)
        req_deg = getattr(config, "required_degree", None) or (job.degree_requirements[0] if getattr(job, "degree_requirements", None) else None)
        required_rank = ComponentScoringService.degree_rank(req_deg)
        if candidate_months >= required_months + 36 or (required_rank and candidate_rank > required_rank):
            items.append(AdjustmentItem(rule_name="OVER_QUALIFICATION", delta_points=5.0, description="Advanced degree or at least three additional years of experience."))
        total = min(cls.CAP, sum(item.delta_points for item in items))
        if sum(item.delta_points for item in items) > cls.CAP:
            items.append(AdjustmentItem(rule_name="BONUS_CAP", delta_points=0, description="Total bonuses capped at 15 points."))
        return round(total, 2), items
