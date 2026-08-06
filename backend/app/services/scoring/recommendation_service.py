from app.schemas.scoring import RecommendationLevel


class RecommendationService:
    @staticmethod
    def recommend(final_score: float, passing_score: float, is_knocked_out: bool = False) -> RecommendationLevel:
        if is_knocked_out: return RecommendationLevel.NOT_RECOMMENDED
        if final_score < passing_score - 15: return RecommendationLevel.NOT_RECOMMENDED
        if final_score < passing_score: return RecommendationLevel.NEEDS_REVIEW
        if final_score < passing_score + 15: return RecommendationLevel.RECOMMENDED
        return RecommendationLevel.STRONG_MATCH
