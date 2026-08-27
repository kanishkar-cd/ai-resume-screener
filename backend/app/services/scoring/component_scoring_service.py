import re
from typing import Any

from app.schemas.scoring import ComponentScoreDetail, ComponentScores
from app.services.pipeline.canonical_dictionaries import (
    CATEGORY_REQUIREMENT_ALIASES, SKILL_CATEGORIES,
)
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

    def score(
        self,
        resume: Any,
        job: Any,
        config: Any,
        projects: list[dict[str, Any]] | None = None,
        match_verdicts: list[Any] | None = None,
    ) -> ComponentScores:
        candidate_skills = list(resume.skills or [])
        job_req_skills = list(getattr(job, "required_skills", None) or [])
        if not job_req_skills:
            job_req_skills = list(getattr(job, "skills", None) or [])
        
        # Only required skills count towards deterministic skill score
        required_skills = self._deduplicate(job_req_skills)
        if config and getattr(config, "mandatory_skills", None):
            required_skills = self._deduplicate([*(config.mandatory_skills or []), *required_skills])

        skills = self._match(candidate_skills, required_skills, "required skills")

        # Experience & contextual responsibilities evaluation
        candidate_months = sum(item.get("duration_months") or 0 for item in (resume.experience or []))
        job_months = max([item.get("minimum_months") or 0 for item in (job.experience_requirements or [])] or [0])
        min_exp = float(getattr(config, "min_experience_years", 0) or 0)
        required_months = max(job_months, round(min_exp * 12))

        # Check for Groq LLM responsibility verdicts
        responsibility_verdicts = [
            v for v in (match_verdicts or [])
            if str(getattr(v, "requirement_id", "")).startswith("responsibility:")
        ]

        # Helper to check if verdict is matched
        def _is_matched(v: Any) -> bool:
            st = getattr(v, "status", None)
            val = getattr(st, "value", st)
            return str(val).upper() == "MATCHED" or str(st).upper() in {"MATCHED", "MATCHSTATUS.MATCHED"}

        if required_months > 0:
            duration_score = min(100.0, candidate_months / required_months * 100)
            if responsibility_verdicts:
                matched_resp = sum(1 for v in responsibility_verdicts if _is_matched(v))
                resp_score = (matched_resp / len(responsibility_verdicts)) * 100.0
                exp_score = round(0.5 * duration_score + 0.5 * resp_score, 2)
                exp_explanation = f"Experience duration is {candidate_months}/{required_months} months; demonstrated {matched_resp}/{len(responsibility_verdicts)} role responsibilities."
            else:
                exp_score = round(duration_score, 2)
                exp_explanation = f"Candidate experience is {candidate_months} months against {required_months} required months."

            experience = ComponentScoreDetail(
                score=exp_score,
                matched_items=[f"{candidate_months} months"],
                missing_items=[] if candidate_months >= required_months else [f"{required_months - candidate_months} months"],
                explanation=exp_explanation,
            )
        elif responsibility_verdicts:
            matched_resp = sum(1 for v in responsibility_verdicts if _is_matched(v))
            resp_score = round((matched_resp / len(responsibility_verdicts)) * 100.0, 2)
            experience = ComponentScoreDetail(
                score=resp_score,
                matched_items=[getattr(v, "requirement_id", "") for v in responsibility_verdicts if _is_matched(v)],
                missing_items=[getattr(v, "requirement_id", "") for v in responsibility_verdicts if not _is_matched(v)],
                explanation=f"Demonstrated {matched_resp} of {len(responsibility_verdicts)} role responsibilities via candidate evidence.",
            )
        else:
            experience = ComponentScoreDetail(
                score=100.0,
                matched_items=[f"{candidate_months} months"],
                missing_items=[],
                explanation=f"Candidate experience is {candidate_months} months against 0 required months (N/A).",
            )

        projects_list = projects if projects is not None else getattr(resume, "projects", [])
        projects_score = self._projects_score(projects_list, job)
        education = self._education_component(resume, job, config)
        certifications = self._certifications_score(resume, job, config)
        languages = self._languages_score(resume, config)

        return ComponentScores(skills=skills, experience=experience, projects=projects_score, education=education, certifications=certifications, languages=languages)

    def _education_component(self, resume: Any, job: Any, config: Any) -> ComponentScoreDetail:
        req_deg = getattr(config, "required_degree", None) or (job.degree_requirements[0] if getattr(job, "degree_requirements", None) else None)
        candidate_degrees = [item.get("degree") for item in (resume.education or []) if item.get("degree")]
        education_score = self._education_score(candidate_degrees, req_deg)
        return ComponentScoreDetail(
            score=education_score, matched_items=candidate_degrees if education_score == 100 else [],
            missing_items=[req_deg] if req_deg and education_score < 100 else [],
            explanation="Education meets the configured requirement." if education_score == 100 else "Candidate degree is below or does not match the requirement.",
        )

    def _projects_score(self, projects: list[dict[str, Any]], job: Any) -> ComponentScoreDetail:
        project_keywords = [k for k in list(job.keywords or []) if k.casefold() not in {t.casefold() for t in DESIGNATIONS}]
        if not project_keywords:
            project_keywords = list(getattr(job, "required_skills", None) or [])
            if not project_keywords:
                project_keywords = list(getattr(job, "skills", None) or [])

        if not project_keywords:
            return ComponentScoreDetail(
                score=100.0,
                matched_items=[],
                missing_items=[],
                explanation="No specific project requirements configured (N/A).",
            )

        if not projects:
            return ComponentScoreDetail(
                score=0.0,
                matched_items=[],
                missing_items=project_keywords,
                explanation="No candidate projects found.",
            )

        # Extract all project terms from technologies, names, and descriptions
        project_terms: list[str] = []
        project_text_blobs: list[str] = []
        for project in projects or []:
            techs = project.get("technologies") or []
            project_terms.extend(techs)
            name = project.get("name") or ""
            if name:
                project_terms.append(name)
            desc = project.get("description") or ""
            if desc:
                project_text_blobs.append(desc)
                # Also tokenize description words
                project_terms.extend(re.findall(r"[A-Za-z0-9+#.]+", desc))

        candidate_keys = self._keys(project_terms)
        combined_text = " ".join([*project_terms, *project_text_blobs]).casefold()

        matched_display: list[str] = []
        missing_display: list[str] = []
        satisfied_groups = 0

        raw_items = self._deduplicate(project_keywords)
        for item in raw_items:
            alternatives = [alt.strip() for alt in re.split(r"\s+(?:or|\/|\|)\s+|\s*,\s*or\s+", item, flags=re.IGNORECASE) if alt.strip()]
            if not alternatives:
                alternatives = [item.strip()]

            matched_alt = None
            for alt in alternatives:
                alt_cf = alt.casefold()
                if alt_cf in candidate_keys:
                    matched_alt = alt
                    break
                # Check for phrase / regex match inside project text
                escaped = re.escape(alt_cf)
                if re.search(rf"(?:\b|_){escaped}(?:\b|_)", combined_text, re.IGNORECASE):
                    matched_alt = alt
                    break

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
            explanation=f"Matched {satisfied_groups} of {len(raw_items)} project competencies.",
        )

    def _certifications_score(self, resume: Any, job: Any, config: Any) -> ComponentScoreDetail:
        req_certs = list(getattr(config, "required_certifications", None) or [])
        if req_certs:
            return self._match(list(resume.certifications or []), req_certs, "required certifications")
        return ComponentScoreDetail(
            score=100.0,
            matched_items=[],
            missing_items=[],
            explanation="No specific certification requirements configured (N/A).",
        )

    def _languages_score(self, resume: Any, config: Any) -> ComponentScoreDetail:
        req_langs = list(getattr(config, "required_languages", None) or [])
        if req_langs:
            return self._match(list(resume.languages or []), req_langs, "required languages")
        return ComponentScoreDetail(
            score=100.0,
            matched_items=[],
            missing_items=[],
            explanation="No specific language requirements configured (N/A).",
        )


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

            matched_alt = None
            for alt in alternatives:
                alt_clean = alt.strip()
                alt_cf = alt_clean.casefold()

                # Check if alternative is a category requirement (e.g. PROGRAMMING_LANGUAGE)
                category_name = alt_clean.upper() if alt_clean.upper() in SKILL_CATEGORIES else (
                    CATEGORY_REQUIREMENT_ALIASES.get(alt_cf)
                )

                if category_name and category_name in SKILL_CATEGORIES:
                    category_members = {m.casefold() for m in SKILL_CATEGORIES[category_name]}
                    # Match if candidate possesses any skill belonging to the category
                    matched_member = next((k for k in candidate_keys if k in category_members), None)
                    if matched_member:
                        orig_skill = next((s for s in candidate if s.strip().casefold() == matched_member), matched_member.title())
                        matched_alt = orig_skill
                        break
                elif alt_cf in candidate_keys:
                    matched_alt = alt_clean
                    break

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
