import re
from typing import Any

from app.schemas.scoring import ComponentScoreDetail, ComponentScores
<<<<<<< Updated upstream
=======
from app.services.pipeline.canonical_dictionaries import (
    CATEGORY_REQUIREMENT_ALIASES, SKILL_ALIASES, SKILL_CATEGORIES,
)
>>>>>>> Stashed changes
from app.services.pipeline.extraction_pipeline import DESIGNATIONS



_TOKEN = re.compile(r"[a-z0-9+#.]+")
_STEM_SUFFIXES = (
    "ization", "isation", "ation", "ition", "izing", "ising", "ized", "ised",
    "ating", "ated", "ates", "ing", "ment", "tion", "sion", "able", "ible", "ness", "ies", "ied", "ed", "es", "ful", "s", "y",
)


def _stem_token(token: str) -> str:
    t = token.casefold().strip()
    if len(t) <= 3:
        return t
    for suffix in _STEM_SUFFIXES:
        if t.endswith(suffix) and len(t) - len(suffix) >= 3:
            return t[:-len(suffix)]
    return t


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

    @staticmethod
    def _match_multiword_concept(concept_text: str, candidate_texts: list[str]) -> str | None:
        """
        Deterministically matches a multi-word skill concept against candidate evidence.
        Ensures all required stemmed concept tokens appear in candidate text with concept proximity.
        Avoids single-word collisions (e.g. Java vs JavaScript).
        """
        concept_tokens = [
            t for t in _TOKEN.findall(concept_text.casefold())
            if len(t) > 1 and t not in {"and", "with", "or", "using", "of", "in", "the", "for"}
        ]
        if len(concept_tokens) < 2:
            return None

        stemmed_concept = [_stem_token(t) for t in concept_tokens]

        for text in candidate_texts:
            if not text:
                continue
            text_tokens = [t for t in _TOKEN.findall(text.casefold()) if len(t) > 1]
            stemmed_text = [_stem_token(t) for t in text_tokens]

            if all(ct in stemmed_text for ct in stemmed_concept):
                indices = [stemmed_text.index(ct) for ct in stemmed_concept if ct in stemmed_text]
                if indices and (max(indices) - min(indices)) <= len(concept_tokens) + 4:
                    return text.strip()
        return None

    def score(
        self,
        resume: Any,
        job: Any,
        config: Any,
        projects: list[dict[str, Any]] | None = None,
        match_verdicts: list[Any] | None = None,
    ) -> ComponentScores:
        candidate_skills = list(dict.fromkeys([
            *(getattr(resume, "skills", None) or []),
            *(getattr(resume, "certifications", None) or []),
            *[t for p in (projects or []) for t in (p.get("technologies") or [])],
            *[t for exp in (getattr(resume, "experience", None) or []) for t in (exp.get("technologies") or [])],
            *[line for exp in (getattr(resume, "experience", None) or []) for line in (exp.get("responsibilities") or []) if line],
            *[exp.get("description") or "" for exp in (getattr(resume, "experience", None) or []) if exp.get("description")],
            *[p.get("description") or "" for p in (projects or []) if p.get("description")],
        ]))
        job_req_skills = list(getattr(job, "required_skills", None) or [])
        if not job_req_skills:
            job_req_skills = list(getattr(job, "skills", None) or [])
        
        # Only required skills count towards deterministic skill score
        required_skills = self._deduplicate(job_req_skills)
        if config and getattr(config, "mandatory_skills", None):
            required_skills = self._deduplicate([*(config.mandatory_skills or []), *required_skills])

        skills = self._match(candidate_skills, required_skills, "required skills")

        def _is_matched(v: Any) -> bool:
            st = getattr(v, "status", None)
            val = getattr(st, "value", st)
            return str(val).upper() == "MATCHED" or str(st).upper() in {"MATCHED", "MATCHSTATUS.MATCHED"}

        # Enrich skills with LLM-confirmed skill verdicts if present
        if match_verdicts and skills.missing_items:
            req_id_to_skill: dict[str, str] = {}
            counter = 1
            for s in required_skills:
                req_id_to_skill[f"skill:{counter}"] = s
                counter += 1

            confirmed_skills = [
                v for v in match_verdicts
                if str(getattr(v, "requirement_id", "")).startswith("skill:") and _is_matched(v)
            ]
            if confirmed_skills:
                confirmed_skill_texts = {
                    req_id_to_skill[str(getattr(cv, "requirement_id", ""))].casefold()
                    for cv in confirmed_skills
                    if str(getattr(cv, "requirement_id", "")) in req_id_to_skill
                }
                new_matched = list(skills.matched_items)
                new_missing = []
                for missing_skill in skills.missing_items:
                    matched_v = False
                    m_cf = missing_skill.casefold()
                    if m_cf in confirmed_skill_texts:
                        matched_v = True
                    else:
                        for cv in confirmed_skills:
                            cv_reasoning = str(getattr(cv, "reasoning", "")).casefold()
                            cv_id = str(getattr(cv, "requirement_id", "")).casefold()
                            if m_cf in cv_reasoning or m_cf in cv_id:
                                matched_v = True
                                break
                    if matched_v:
                        new_matched.append(missing_skill)
                    else:
                        new_missing.append(missing_skill)

                if len(new_matched) > len(skills.matched_items):
                    skills = ComponentScoreDetail(
                        score=round(min(100.0, (len(new_matched) / len(required_skills)) * 100.0), 2) if required_skills else 100.0,
                        matched_items=new_matched,
                        missing_items=new_missing,
                        explanation=f"Matched {len(new_matched)} of {len(required_skills)} required skills ({len(new_matched)} satisfied deterministically/semantically).",
                    )

        # ── Responsibilities Component (25% weight) ─────────────────────────
        responsibility_verdicts = [
            v for v in (match_verdicts or [])
            if str(getattr(v, "requirement_id", "")).startswith("responsibility:")
        ]
        job_responsibilities = list(getattr(job, "responsibilities", None) or [])

        if responsibility_verdicts:
            matched_verdicts = [v for v in responsibility_verdicts if _is_matched(v)]
            matched_resp = len(matched_verdicts)
            resp_score = round((matched_resp / len(responsibility_verdicts)) * 100.0, 2)
            responsibilities = ComponentScoreDetail(
                score=resp_score,
                matched_items=[getattr(v, "requirement_id", "") for v in matched_verdicts],
                missing_items=[getattr(v, "requirement_id", "") for v in responsibility_verdicts if not _is_matched(v)],
                explanation=f"Demonstrated {matched_resp} of {len(responsibility_verdicts)} role responsibilities via candidate evidence.",
            )
        elif job_responsibilities:
            # Fallback when LLM verdicts are absent
            exp_text = " ".join([
                *[exp.get("description") or "" for exp in (getattr(resume, "experience", None) or [])],
                *[line for exp in (getattr(resume, "experience", None) or []) for line in (exp.get("responsibilities") or [])],
            ]).casefold()
            matched_r = [r for r in job_responsibilities if any(w in exp_text for w in r.casefold().split() if len(w) > 3)]
            resp_score = round(min(100.0, (len(matched_r) / len(job_responsibilities)) * 100.0), 2)
            responsibilities = ComponentScoreDetail(
                score=resp_score,
                matched_items=matched_r,
                missing_items=[r for r in job_responsibilities if r not in matched_r],
                explanation=f"Demonstrated {len(matched_r)} of {len(job_responsibilities)} role responsibilities.",
            )
        else:
            responsibilities = ComponentScoreDetail(
                score=100.0,
                matched_items=[],
                missing_items=[],
                explanation="No specific role responsibilities configured (N/A).",
            )

        # ── Preferred Skills Component (15% weight) ─────────────────────────
        job_pref_skills = list(getattr(job, "preferred_skills", None) or [])
        if job_pref_skills:
            preferred_skills = self._match(candidate_skills, job_pref_skills, "preferred skills")

            # Enrich preferred_skills with LLM-confirmed skill verdicts if present
            if match_verdicts and preferred_skills.missing_items:
                req_id_to_preferred: dict[str, str] = {}
                offset = len(required_skills)
                for i, s in enumerate(job_pref_skills):
                    req_id_to_preferred[f"skill:{offset + i + 1}"] = s

                confirmed_skills = [
                    v for v in match_verdicts
                    if str(getattr(v, "requirement_id", "")).startswith("skill:") and _is_matched(v)
                ]
                if confirmed_skills:
                    confirmed_pref_texts = {
                        req_id_to_preferred[str(getattr(cv, "requirement_id", ""))].casefold()
                        for cv in confirmed_skills
                        if str(getattr(cv, "requirement_id", "")) in req_id_to_preferred
                    }
                    new_pref_matched = list(preferred_skills.matched_items)
                    new_pref_missing = []
                    for missing_skill in preferred_skills.missing_items:
                        matched_v = False
                        m_cf = missing_skill.casefold()
                        if m_cf in confirmed_pref_texts:
                            matched_v = True
                        else:
                            for cv in confirmed_skills:
                                cv_reasoning = str(getattr(cv, "reasoning", "")).casefold()
                                cv_id = str(getattr(cv, "requirement_id", "")).casefold()
                                if m_cf in cv_reasoning or m_cf in cv_id:
                                    matched_v = True
                                    break
                        if matched_v:
                            new_pref_matched.append(missing_skill)
                        else:
                            new_pref_missing.append(missing_skill)

                    if len(new_pref_matched) > len(preferred_skills.matched_items):
                        preferred_skills = ComponentScoreDetail(
                            score=round(min(100.0, (len(new_pref_matched) / len(job_pref_skills)) * 100.0), 2),
                            matched_items=new_pref_matched,
                            missing_items=new_pref_missing,
                            explanation=f"Matched {len(new_pref_matched)} of {len(job_pref_skills)} preferred skills ({len(new_pref_matched)} satisfied deterministically/semantically).",
                        )
        else:
            preferred_skills = ComponentScoreDetail(
                score=100.0,
                matched_items=[],
                missing_items=[],
                explanation="No preferred skills configured (N/A).",
            )

        # ── Experience Duration Component (5% weight) ───────────────────────
        candidate_months = sum(item.get("duration_months") or 0 for item in (getattr(resume, "experience", None) or []))
        job_months = max([item.get("minimum_months") or 0 for item in (getattr(job, "experience_requirements", None) or [])] or [0])
        min_exp = float(getattr(config, "min_experience_years", 0) or 0)
        required_months = max(job_months, round(min_exp * 12))

        if required_months > 0:
            duration_score = round(min(100.0, (candidate_months / required_months) * 100.0), 2)
            experience = ComponentScoreDetail(
                score=duration_score,
                matched_items=[f"{candidate_months} months"],
                missing_items=[] if candidate_months >= required_months else [f"{required_months - candidate_months} months"],
                explanation=f"Candidate experience is {candidate_months} months against {required_months} required months.",
            )
        else:
            experience = ComponentScoreDetail(
                score=100.0,
                matched_items=[f"{candidate_months} months"],
                missing_items=[],
                explanation=f"Candidate experience is {candidate_months} months against 0 required months (N/A).",
            )

        projects_list = list(projects if projects is not None else (getattr(resume, "projects", []) or []))
        if not projects_list and getattr(resume, "experience", None):
            for exp in resume.experience or []:
                desc = exp.get("description") or ""
                resps = exp.get("responsibilities") or []
                full_exp_text = " ".join(v for v in [desc, *resps] if v).strip()
                if re.search(r"\b(?:built|developed|designed|implemented|created|architected|delivered)\b.*?\b(?:application|app|platform|system|portal|service|microservices|dashboard|website|store|api|pipeline)\b", full_exp_text, re.I):
                    projects_list.append({
                        "name": exp.get("title") or exp.get("job_title") or exp.get("designation") or "Project Deliverable",
                        "description": full_exp_text,
                        "technologies": exp.get("technologies") or [],
                    })
        projects_score = self._projects_score(projects_list, job)
        education = self._education_component(resume, job, config)
        certifications = self._certifications_score(resume, job, config)
        languages = self._languages_score(resume, config)

        return ComponentScores(
            skills=skills,
            responsibilities=responsibilities,
            projects=projects_score,
            preferred_skills=preferred_skills,
            experience=experience,
            education=education,
            certifications=certifications,
            languages=languages,
        )

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
        project_keywords = [k for k in list(getattr(job, "project_requirements", None) or []) if k]
        if not project_keywords:
            project_keywords = [k for k in list(getattr(job, "keywords", None) or []) if k.casefold() not in {t.casefold() for t in DESIGNATIONS}]

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
            such_parts = []
            such_match = re.search(r"\b(?:such\s+as|like|e\.g\.?|including)\s+(.+)$", item, re.I)
            if such_match:
                such_parts_raw = re.split(r"[,;/]|\s+or\s+|\s+and\s+", such_match.group(1).strip())
                such_parts = [p.strip() for p in such_parts_raw if p.strip()]

            raw_alts = re.split(r"\s*(?:\/|\|)\s*|\s+(?:or|and)\s+|\s*,\s*(?:or|and)?\s*|\s*;\s*", item, flags=re.IGNORECASE)
            alternatives = list(dict.fromkeys([a.strip() for a in [*raw_alts, *such_parts, item] if a.strip()]))

<<<<<<< Updated upstream
            # Check if any alternative is present in the candidate's skills/items
            matched_alt = next((alt for alt in alternatives if alt.casefold() in candidate_keys), None)
=======
            matched_alt = None
            for alt in alternatives:
                alt_clean = alt.strip()
                alt_cf = alt_clean.casefold()

                # Check if alternative is a category requirement (e.g. PROGRAMMING_LANGUAGE, RELATIONAL_DATABASE, CLOUD_PLATFORMS)
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
                else:
                    canonical_alt = SKILL_ALIASES.get(alt_cf)
                    if canonical_alt and canonical_alt.casefold() in candidate_keys:
                        matched_alt = canonical_alt
                        break
                    cand_matched = next(
                        (
                            orig for orig in candidate
                            if (ck := orig.strip().casefold()) in candidate_keys and (
                                (can_ck := SKILL_ALIASES.get(ck)) and (
                                    can_ck.casefold() == alt_cf or
                                    (canonical_alt and can_ck.casefold() == canonical_alt.casefold())
                                )
                            )
                        ),
                        None
                    )
                    if cand_matched:
                        matched_alt = cand_matched
                        break

                    aliases_for_alt = {
                        k for k, v in SKILL_ALIASES.items()
                        if v.casefold() == alt_cf or (canonical_alt and v.casefold() == canonical_alt.casefold())
                    }
                    if aliases_for_alt:
                        for text in candidate:
                            if not text:
                                continue
                            t_cf = text.casefold()
                            for alias_k in aliases_for_alt:
                                if len(alias_k) >= 3 and re.search(rf"\b{re.escape(alias_k)}\b", t_cf):
                                    matched_alt = alt_clean
                                    break
                            if matched_alt:
                                break

                    if matched_alt:
                        break

                    multi_match = self._match_multiword_concept(alt_clean, candidate)
                    if multi_match:
                        matched_alt = alt_clean
                        break
>>>>>>> Stashed changes

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
