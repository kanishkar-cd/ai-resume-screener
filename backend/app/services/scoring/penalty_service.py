from typing import Any
from app.schemas.scoring import AdjustmentItem, ComponentScores


class PenaltyService:
    CAP = 0.0

    @classmethod
    def calculate(cls, components: ComponentScores, config: Any = None) -> tuple[float, list[AdjustmentItem]]:
        """
        Penalties are completely disabled.
        Returns 0.0 total penalty and an empty list of adjustments.
        """
        return 0.0, []

