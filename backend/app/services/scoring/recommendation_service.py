from app.schemas.scoring import RecommendationLevel


class RecommendationService:
    @staticmethod
    def recommend(
        final_score: float,
        passing_score: float = 70.0,
        is_knocked_out: bool = False,
        use_absolute_thresholds: bool = True,
    ) -> RecommendationLevel:
        if is_knocked_out:
            return RecommendationLevel.REJECT

        if use_absolute_thresholds:
            if final_score >= 85:
                return RecommendationLevel.SHORTLIST
            if final_score >= 70:
                return RecommendationLevel.REVIEW
            if final_score >= 50:
                return RecommendationLevel.CONSIDER
            return RecommendationLevel.REJECT

        if final_score < passing_score - 15:
            return RecommendationLevel.REJECT
        if final_score < passing_score:
            return RecommendationLevel.CONSIDER
        if final_score < passing_score + 15:
            return RecommendationLevel.REVIEW
        return RecommendationLevel.SHORTLIST


