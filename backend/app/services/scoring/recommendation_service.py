from app.schemas.scoring import RecommendationLevel


class RecommendationService:
    @staticmethod
    def recommend(
        final_score: float,
        passing_score: float = 70.0,
        is_knocked_out: bool = False,
        use_absolute_thresholds: bool = False,
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

        if final_score < passing_score:
            return RecommendationLevel.REJECT

        shortlist_threshold = max(75.0, passing_score + 15.0)
        if final_score >= shortlist_threshold:
            return RecommendationLevel.SHORTLIST

        review_threshold = max(60.0, passing_score + 5.0)
        if final_score >= review_threshold:
            return RecommendationLevel.REVIEW

        return RecommendationLevel.CONSIDER


