import re
from typing import Any

from app.schemas.scoring import ComponentScoreDetail, ComponentScores
from app.services.pipeline.extraction_pipeline import DESIGNATIONS



class ComponentScoringService:
    DEGREE_RANKS = {
        "high school": 1, "associate": 2, "bachelor of science": 3,
        "bachelor s degree": 3,
        "bachelor of engineering": 3, "bachelor of technology": 3,
        "master of science": 4, "master of engineering": 4,
        "master of technology": 4, "master of business administration": 4,
        "doctor of philosophy": 5,
    }

    @staticmethod
    def _keys(values: list[str]) -> set[str]:
        return {value.strip().casefold() for value in values if value.strip()}

    @staticmethod
    def _deduplicate(values: list[str]) -> list[str]:
        canonical: dict[str, str] = {}
        for value in values:
            stripped = value.strip()
            if stripped:
                canonical.setdefault(stripped.casefold(), stripped)
        return list(canonical.values())

    @staticmethod
    def _percentage(matched: list[str], required: list[str]) -> float:
        return round(min(100.0, len(matched) / len(required) * 100), 2) if required else 100.0

    def score(self, resume: Any, job: Any, config: Any, projects: list[dict[str, Any]] | None = None) -> ComponentScores:
        candidate_skills = list(resume.skills or [])
        # Mandatory configuration owns the canonical display casing when the JD
        # contains the same skill with a different case.
        required_skills = self._deduplicate([*(config.mandatory_skills or []), *(job.skills or [])])
        skills = self._match(candidate_skills, required_skills, "required skills")

        candidate_months = sum(item.get("duration_months") or 0 for item in (resume.experience or []))
        job_months = max([item.get("minimum_months") or 0 for item in (job.experience_requirements or [])] or [0])
        required_months = max(job_months, round(float(config.min_experience_years) * 12))
        experience_score = min(100.0, candidate_months / required_months * 100) if required_months else 100.0
        experience = ComponentScoreDetail(
            score=round(experience_score, 2), matched_items=[f"{candidate_months} months"],
            missing_items=[] if candidate_months >= required_months else [f"{required_months - candidate_months} months"],
            explanation=f"Candidate experience is {candidate_months} months against {required_months} required months.",
        )

        required_degree = config.required_degree or (job.degree_requirements[0] if job.degree_requirements else None)
        candidate_degrees = [item.get("degree") for item in (resume.education or []) if item.get("degree")]
        education_score = self._education_score(candidate_degrees, required_degree)
        education = ComponentScoreDetail(
            score=education_score, matched_items=candidate_degrees if education_score == 100 else [],
            missing_items=[required_degree] if required_degree and education_score < 100 else [],
            explanation="Education meets the configured requirement." if education_score == 100 else "Candidate degree is below or does not match the requirement.",
        )

        project_terms: list[str] = []
        for project in projects or []:
            project_terms.extend(project.get("technologies") or [])
            if project.get("name"):
                project_terms.append(project["name"])

        # Project keyword matching strictly against project names and technologies (excluding job titles)
        project_keywords = [k for k in list(job.keywords or []) if k.casefold() not in {t.casefold() for t in DESIGNATIONS}]
        project_score = self._match(project_terms, project_keywords, "job keywords")

        req_certs = list(config.required_certifications or [])
        if req_certs:
            certifications = self._match(list(resume.certifications or []), req_certs, "required certifications")
        else:
            certifications = ComponentScoreDetail(
                score=100.0,
                matched_items=[],
                missing_items=[],
                explanation="No specific certification requirements configured (N/A).",
            )

        req_langs = list(getattr(config, "required_languages", None) or [])
        if req_langs:
            languages = self._match(list(resume.languages or []), req_langs, "required languages")
        else:
            languages = ComponentScoreDetail(
                score=100.0,
                matched_items=[],
                missing_items=[],
                explanation="No specific language requirements configured (N/A).",
            )

        return ComponentScores(skills=skills, experience=experience, projects=project_score, education=education, certifications=certifications, languages=languages)


    def _match(self, candidate: list[str], required: list[str], label: str) -> ComponentScoreDetail:
        required = self._deduplicate(required)
        candidate_keys = self._keys(candidate)
        matched = [item for item in required if item.strip().casefold() in candidate_keys]
        missing = [item for item in required if item.strip().casefold() not in candidate_keys]
        return ComponentScoreDetail(score=self._percentage(matched, required), matched_items=matched, missing_items=missing, explanation=f"Matched {len(matched)} of {len(required)} {label}.")

    @classmethod
    def degree_rank(cls, degree: str | None) -> int:
        if not degree: return 0
        key = re.sub(r"[^a-z0-9]+", " ", degree.casefold()).strip()
        if key in {"be", "b e", "btech", "b tech"}:
            return 3
        return max((rank for name, rank in cls.DEGREE_RANKS.items() if name in key), default=0)

    @classmethod
    def _education_score(cls, candidate: list[str], required: str | None) -> float:
        if not required: return 100.0
        required_rank = cls.degree_rank(required)
        candidate_rank = max((cls.degree_rank(value) for value in candidate), default=0)
        if required_rank and candidate_rank >= required_rank: return 100.0
        if any(value.casefold() == required.casefold() for value in candidate): return 100.0
        return 50.0
