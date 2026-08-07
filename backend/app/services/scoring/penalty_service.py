from typing import Any
from app.schemas.scoring import AdjustmentItem, ComponentScores


class PenaltyService:
    CAP = 30.0

    @classmethod
    def calculate(cls, components: ComponentScores, config: Any) -> tuple[float, list[AdjustmentItem]]:
        items: list[AdjustmentItem] = []
        if components.experience.missing_items:
            try: deficit_years = float(components.experience.missing_items[0].split()[0]) / 12
            except (ValueError, IndexError): deficit_years = 0
            points = min(cls.CAP, deficit_years * 5)
            if points: items.append(AdjustmentItem(rule_name="EXPERIENCE_DEFICIT", delta_points=-round(points, 2), description="5 points per year below required experience."))
        hard_skill = any(rule.get("rule_type") == "MISSING_MANDATORY_SKILL" and rule.get("enabled", True) for rule in (config.knockout_rules or []))
        if not hard_skill:
            mandatory = {value.casefold() for value in config.mandatory_skills}
            count = sum(value.casefold() in mandatory for value in components.skills.missing_items)
            if count: items.append(AdjustmentItem(rule_name="MISSING_MANDATORY_SKILL", delta_points=-10.0 * count, description="10 points per missing mandatory skill."))
        total = min(cls.CAP, sum(abs(item.delta_points) for item in items))
        if sum(abs(item.delta_points) for item in items) > cls.CAP:
            items.append(AdjustmentItem(rule_name="PENALTY_CAP", delta_points=0, description="Total penalties capped at 30 points."))
        return round(total, 2), items
