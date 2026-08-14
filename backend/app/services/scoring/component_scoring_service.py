import re
from typing import Any

from app.schemas.scoring import ComponentScoreDetail, ComponentScores
from app.services.pipeline.extraction_pipeline import DESIGNATIONS



class ComponentScoringService:
    DEGREE_RANKS = {
        "high school": 1, "associate": 2,
        "bachelor of science": 3, "bachelor s degree": 3,
        "bachelor of engineering": 3, "bachelor of technology": 3,
        "b sc": 3, "b s": 3, "b com": 3, "bca": 3, "b tech": 3, "b e": 3, "be": 3,
        "master of science": 4, "master of engineering": 4,
        "master of technology": 4, "master of business administration": 4,
        "m sc": 4, "m s": 4, "mca": 4, "mba": 4,
        "doctor of philosophy": 5, "phd": 5,
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
        job_req_skills = list(getattr(job, "required_skills", None) or [])
        if not job_req_skills:
            job_req_skills = list(getattr(job, "skills", None) or [])
        required_skills = self._deduplicate([*(config.mandatory_skills or []), *job_req_skills])
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


    def _match_groups(self, candidate: list[str], required_items: list[str], label: str) -> ComponentScoreDetail:
        """
        Match candidate items against required requirements.
        Supports OR alternative groups formatted as "A / B / C" or "A or B or C".
        Each alternative group counts as 1 requirement item. Matching any alternative satisfies the group.
        """
        candidate_keys = self._keys(candidate)
        matched_display: list[str] = []
        missing_display: list[str] = []
        satisfied_groups = 0

        # Clean and deduplicate requirement items while preserving group structure
        raw_items = self._deduplicate(required_items)
        if not raw_items:
            return ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=f"No {label} required.")

        for item in raw_items:
            # Parse alternative choices within the requirement line
            alternatives = [alt.strip() for alt in re.split(r"\s+(?:or|\/|\|)\s+|\s*,\s*or\s+", item, flags=re.IGNORECASE) if alt.strip()]
            if not alternatives:
                alternatives = [item.strip()]

            # Check if any alternative is present in the candidate's skills/items
            matched_alt = next((alt for alt in alternatives if alt.casefold() in candidate_keys), None)

            if matched_alt:
                satisfied_groups += 1
                matched_display.append(matched_alt)
            else:
                missing_display.append(item)

        score = round(min(100.0, (satisfied_groups / len(raw_items)) * 100.0), 2)
        return ComponentScoreDetail(
            score=score,
            matched_items=matched_display,
            missing_items=missing_display,
            explanation=f"Matched {satisfied_groups} of {len(raw_items)} {label}.",
        )

    def _match(self, candidate: list[str], required: list[str], label: str) -> ComponentScoreDetail:
        return self._match_groups(candidate, required, label)

    @classmethod
    def degree_rank(cls, degree: str | None) -> int:
        if not degree: return 0
        key = re.sub(r"[^a-z0-9]+", " ", degree.casefold()).strip()
        if key in {"be", "b e", "btech", "b tech", "b sc", "b s", "b com", "bca"}:
            return 3
        if key in {"m sc", "m s", "mca", "mba"}:
            return 4
        return max((rank for name, rank in cls.DEGREE_RANKS.items() if name in key), default=0)

    @classmethod
    def _education_score(cls, candidate: list[str], required: str | None) -> float:
        if not required: return 100.0
        required_rank = cls.degree_rank(required)
        candidate_rank = max((cls.degree_rank(value) for value in candidate), default=0)
        if required_rank and candidate_rank >= required_rank: return 100.0
        if any(value.casefold() == required.casefold() for value in candidate): return 100.0
        return 50.0
