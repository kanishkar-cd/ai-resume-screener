from typing import Any

from app.schemas.insights import CandidateInsightCreate


COMPONENT_LABELS = {
    "skills": "Skills", "experience": "Experience", "projects": "Projects",
    "education": "Education", "certifications": "Certifications", "languages": "Languages",
}


class SummaryGenerator:
    @staticmethod
    def generate(extracted: Any, normalized: Any, score: Any, rank: Any | None) -> str:
        name = extracted.candidate_name or "Anonymous candidate"
        title = extracted.designation or (normalized.job_titles[0] if normalized.job_titles else "candidate")
        months = sum(item.get("duration_months") or 0 for item in normalized.experience)
        experience = f"{months / 12:.1f} years of recorded experience" if months else "no quantified experience"
        rank_text = f" and is ranked #{rank.rank_position}" if rank else ""
        return f"{name} is a {title} with {experience}, a final score of {float(score.final_score):.2f}{rank_text}."


class StrengthGenerator:
    @staticmethod
    def generate(component_scores: dict[str, Any]) -> list[str]:
        return [f"{COMPONENT_LABELS[name]} scored {float(detail['score']):.2f}%." for name, detail in component_scores.items() if float(detail["score"]) >= 80]


class WeaknessGenerator:
    @staticmethod
    def generate(component_scores: dict[str, Any]) -> list[str]:
        return [f"{COMPONENT_LABELS[name]} scored {float(detail['score']):.2f}%." for name, detail in component_scores.items() if float(detail["score"]) < 60]


class SkillGapGenerator:
    @staticmethod
    def generate(component_scores: dict[str, Any]) -> tuple[list[str], list[str]]:
        skills = component_scores.get("skills", {})
        return list(skills.get("matched_items", [])), list(skills.get("missing_items", []))


class RecommendationGenerator:
    @staticmethod
    def generate(score: Any) -> str:
        if score.is_knocked_out:
            return f"NOT_RECOMMENDED because a knockout rule applied: {score.knockout_reason or 'unspecified rule'}."
        return f"{score.recommendation.value} based on a final score of {float(score.final_score):.2f}, confidence of {float(score.confidence):.2f}%, and the configured decision thresholds."


class ImprovementGenerator:
    @staticmethod
    def generate(missing_skills: list[str], component_scores: dict[str, Any]) -> list[str]:
        suggestions = [f"Develop demonstrable proficiency in {skill}." for skill in missing_skills]
        suggestions.extend(f"Strengthen evidence for {COMPONENT_LABELS[name].lower()}." for name, detail in component_scores.items() if float(detail["score"]) < 60 and name != "skills")
        return suggestions or ["Maintain the documented strengths and keep experience evidence current."]


class InsightBuilder:
    def build(self, document_id: Any, project_id: Any, extracted: Any, normalized: Any, score: Any, rank: Any | None = None) -> CandidateInsightCreate:
        components = score.component_scores or {}
        matched, missing = SkillGapGenerator.generate(components)
        weighted = ", ".join(f"{COMPONENT_LABELS[name]} {float(value):.2f}" for name, value in (score.weighted_scores or {}).items())
        explanation = (
            f"Raw total {float(score.raw_total_score):.2f}; weighted contributions: {weighted}. "
            f"Weighted total {float(score.weighted_total_score):.2f}, penalties {float(score.penalty_total):.2f}, "
            f"bonuses {float(score.bonus_total):.2f}, final score {float(score.final_score):.2f}."
        )
        return CandidateInsightCreate(
            document_id=document_id, project_id=project_id,
            summary=SummaryGenerator.generate(extracted, normalized, score, rank),
            strengths=StrengthGenerator.generate(components), weaknesses=WeaknessGenerator.generate(components),
            matched_skills=matched, missing_skills=missing, score_explanation=explanation,
            recommendation_reason=RecommendationGenerator.generate(score),
            improvement_suggestions=ImprovementGenerator.generate(missing, components),
        )
