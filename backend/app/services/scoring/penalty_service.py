from typing import Any
from app.schemas.scoring import AdjustmentItem, ComponentScores


class PenaltyService:
    CAP = 30.0

    @classmethod
    def calculate(cls, components: ComponentScores, config: Any) -> tuple[float, list[AdjustmentItem]]:
        items: list[AdjustmentItem] = []
        # Experience duration weight removed (0% direct weighted contribution)
        knockout_rules = getattr(config, "knockout_rules", None) or []
        hard_skill = any(rule.get("rule_type") == "MISSING_MANDATORY_SKILL" and rule.get("enabled", True) for rule in knockout_rules)
        if not hard_skill:
            mandatory_skills = getattr(config, "mandatory_skills", None) or []
            mandatory = {value.casefold() for value in mandatory_skills}
            count = sum(value.casefold() in mandatory for value in components.skills.missing_items)
            if count: items.append(AdjustmentItem(rule_name="MISSING_MANDATORY_SKILL", delta_points=-10.0 * count, description="10 points per missing mandatory skill."))
        total = min(cls.CAP, sum(abs(item.delta_points) for item in items))
        if sum(abs(item.delta_points) for item in items) > cls.CAP:
            items.append(AdjustmentItem(rule_name="PENALTY_CAP", delta_points=0, description="Total penalties capped at 30 points."))
        return round(total, 2), items
