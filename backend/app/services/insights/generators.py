from typing import Any

from app.schemas.insights import CandidateInsightCreate


COMPONENT_LABELS = {
    "skills": "Skills", "experience": "Experience", "projects": "Projects",
    "education": "Education", "certifications": "Certifications", "languages": "Languages",
}


def _is_not_applicable(name: str, detail: dict[str, Any]) -> bool:
    explanation = str(detail.get("explanation") or "").casefold()
    return "(n/a)" in explanation or (
        name == "experience" and "against 0 required months" in explanation
    )


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
        return [
            f"{COMPONENT_LABELS[name]} scored {float(detail['score']):.2f}%."
            for name, detail in component_scores.items()
            if not _is_not_applicable(name, detail) and float(detail["score"]) >= 80
        ]


class WeaknessGenerator:
    @staticmethod
    def generate(component_scores: dict[str, Any]) -> list[str]:
        return [
            f"{COMPONENT_LABELS[name]} scored {float(detail['score']):.2f}%."
            for name, detail in component_scores.items()
            if not _is_not_applicable(name, detail) and float(detail["score"]) < 60
        ]


class SkillGapGenerator:
    @staticmethod
    def generate(component_scores: dict[str, Any]) -> tuple[list[str], list[str]]:
        skills = component_scores.get("skills", {})
        return list(skills.get("matched_items", [])), list(skills.get("missing_items", []))


class RecommendationGenerator:
    @staticmethod
    def generate(score: Any) -> str:
        if score.is_knocked_out:
            reason = score.knockout_reason or "unspecified mandatory requirement"
            return f"REJECT because a mandatory requirement was not satisfied: {reason}."
        final_score = float(score.final_score)
        recommendation = score.recommendation.value
        if recommendation == "SHORTLIST":
            rule = "is 85 or above"
        elif recommendation == "REVIEW":
            rule = "falls within the current 70–84.99 recommendation band"
        elif recommendation == "CONSIDER":
            rule = "falls within the current 50–69.99 recommendation band"
        else:
            rule = "falls below the current recommendation threshold of 50"
        return f"{recommendation} because the final score of {final_score:.2f} {rule}."


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
        not_applicable = [
            f"{COMPONENT_LABELS[name]}: No JD requirement"
            for name, detail in components.items() if _is_not_applicable(name, detail)
        ]
        na_text = f" Not applicable: {'; '.join(not_applicable)}." if not_applicable else ""
        explanation = (
            f"Raw total {float(score.raw_total_score):.2f}; weighted contributions: {weighted}. "
            f"Weighted total {float(score.weighted_total_score):.2f}, penalties {float(score.penalty_total):.2f}, "
            f"bonuses {float(score.bonus_total):.2f}, final score {float(score.final_score):.2f}."
            f"{na_text}"
        )
        return CandidateInsightCreate(
            document_id=document_id, project_id=project_id,
            summary=SummaryGenerator.generate(extracted, normalized, score, rank),
            strengths=StrengthGenerator.generate(components), weaknesses=WeaknessGenerator.generate(components),
            matched_skills=matched, missing_skills=missing, score_explanation=explanation,
            recommendation_reason=RecommendationGenerator.generate(score),
            improvement_suggestions=ImprovementGenerator.generate(missing, components),
        )
