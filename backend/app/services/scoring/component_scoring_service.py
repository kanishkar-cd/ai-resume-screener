import re
from typing import Any

from app.services.pipeline.extraction_pipeline import DESIGNATIONS
from app.schemas.scoring import ComponentScoreDetail, ComponentScores
from app.services.pipeline.canonical_dictionaries import (
    CATEGORY_REQUIREMENT_ALIASES, SKILL_ALIASES, SKILL_CATEGORIES,
)




_TOKEN = re.compile(r"[a-z0-9+#.]+")
_STEM_SUFFIXES = (
    "ization", "isation", "ation", "ition", "izing", "ising", "ized", "ised",
    "ating", "ated", "ates", "ing", "ment", "tion", "sion", "able", "ible", "ness", "ies", "ied", "ed", "es", "ful", "s", "y",
)


_IRREGULAR_VERBS = {
    "built": "build", "led": "lead", "wrote": "write", "ran": "run", "held": "hold",
    "made": "make", "analyzed": "analyze", "analysed": "analyze", "monitored": "monitor",
    "documented": "document", "managed": "manage", "developed": "develop", "deployed": "deploy",
    "maintained": "maintain", "investigated": "investigate", "configured": "configure",
}


def _stem_token(token: str) -> str:
    t = token.casefold().strip()
    if t in _IRREGULAR_VERBS:
        return _IRREGULAR_VERBS[t]
    if len(t) <= 3:
        return t
    for suffix in _STEM_SUFFIXES:
        if t.endswith(suffix) and len(t) - len(suffix) >= 3:
            return t[:-len(suffix)]
    return t


def _clean_req_text(text: str) -> str:
    t = text.strip()
    t = re.sub(
        r"^(?:experience\s+with|knowledge\s+of|proficiency\s+in|familiarity\s+with|understanding\s+of|hands-on\s+with|ability\s+to|exposure\s+to|working\s+with|skills\s+in|proven\s+track\s+record\s+in|demonstrated\s+experience\s+in)\s+",
        "", t, flags=re.I
    ).strip()
    t = re.sub(
        r"^(?:strong|solid|basic|good|deep|fundamental|foundational|practical|advanced|in-depth|hands-on|proven|demonstrated|prior|working)\s+(?:programming\s+fundamentals\s+in|fundamentals\s+in|programming\s+in|knowledge\s+of|understanding\s+of|experience\s+with|proficiency\s+in|familiarity\s+with|skills\s+in|concepts\s+in|exposure\s+to|background\s+in)?\s*",
        "", t, flags=re.I
    ).strip()
    t = re.sub(r"^(?:basic|strong|solid|good|working|advanced|fundamental|practical)\s+", "", t, flags=re.I).strip()
    t = re.sub(r"\s*\([^)]*\)?$", "", t).strip()
    tokens = t.split()
    if len(tokens) > 1 and tokens[-1].lower() in {"fundamentals", "concepts", "principles", "basics", "experience", "skills", "knowledge", "ability"}:
        t = " ".join(tokens[:-1]).strip()
    return t


class ComponentScoringService:

    DEGREE_RANKS = {
        "high school": 1, "associate": 2,
        # Generic bachelor-level (catches "Bachelor's Degree", "bachelor degree", etc.)
        "bachelor": 3,
        "bachelor of science": 3, "bachelor s degree": 3,
        "bachelor of engineering": 3, "bachelor of technology": 3,
        "b sc": 3, "b s": 3, "b com": 3, "bca": 3, "b tech": 3, "b e": 3, "be": 3,
        # Generic master-level (catches "Master's Degree", "master degree", etc.)
        "master": 4,
        "master of science": 4, "master of engineering": 4,
        "master s degree": 4, "master degree": 4,
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
        Deterministically matches a multi-word skill or responsibility concept against candidate evidence.
        Ensures all required stemmed concept tokens appear in candidate text with concept proximity.
        Avoids single-word collisions (e.g. Java vs JavaScript).
        """
        stop_words = {
            "and", "with", "or", "using", "of", "in", "the", "for", "to", "a", "an",
            "on", "from", "by", "as", "at", "during", "across", "into", "through",
        }
        concept_tokens = [
            t for t in _TOKEN.findall(concept_text.casefold())
            if len(t) > 1 and t not in stop_words
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
                if indices and (max(indices) - min(indices)) <= len(concept_tokens) + 8:
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
        raw_certs = getattr(resume, "certifications", None) or []
        cert_names = [(c.get("name") or c.get("title") or "") if isinstance(c, dict) else str(c).strip() for c in raw_certs]
        cert_names = [c for c in cert_names if c]
        summary_text = str(getattr(resume, "summary", None) or "").strip()
        candidate_skills = list(dict.fromkeys([
            *[str(s).strip() for s in (getattr(resume, "skills", None) or []) if str(s).strip()],
            *cert_names,
            *[t for p in (projects or []) for t in (p.get("technologies") or [])],
            *[t for exp in (getattr(resume, "experience", None) or []) for t in (exp.get("technologies") or [])],
            *[line for exp in (getattr(resume, "experience", None) or []) for line in (exp.get("responsibilities") or []) if line],
            *[exp.get("description") or "" for exp in (getattr(resume, "experience", None) or []) if exp.get("description")],
            *[p.get("description") or "" for p in (projects or []) if p.get("description")],
            *([summary_text] if summary_text else []),
        ]))
        job_req_skills = list(getattr(job, "required_skills", None) or [])
        if not job_req_skills:
            job_req_skills = list(getattr(job, "skills", None) or [])
        
        # Only required skills count towards deterministic skill score
        required_skills = self._deduplicate(job_req_skills)
        if config and getattr(config, "mandatory_skills", None):
            required_skills = self._deduplicate([*(config.mandatory_skills or []), *required_skills])

        skills = self._match(candidate_skills, required_skills, "required skills")

        IMPORTANCE_WEIGHTS = {"critical": 3.0, "important": 2.0, "minor": 1.0}

        def _is_matched(v: Any) -> bool:
            st = getattr(v, "status", None)
            val = getattr(st, "value", st)
            mth = getattr(v, "method", None)
            mth_val = getattr(mth, "value", mth)
            return (
                str(val).upper() in {"MATCHED", "CONFIRMED", "AI_CONFIRMED", "MATCHSTATUS.MATCHED"}
                or str(st).upper() in {"MATCHED", "CONFIRMED", "AI_CONFIRMED", "MATCHSTATUS.MATCHED"}
                or str(mth_val).lower() == "llm_confirmed"
            )

        # Importance-weighted continuous skills scoring
        if match_verdicts and required_skills:
            req_id_to_skill: dict[str, str] = {}
            for i, s in enumerate(required_skills, 1):
                req_id_to_skill[f"skill:{i}"] = s
                req_id_to_skill[f"required_skill:{i}"] = s

            skill_verdict_map: dict[str, Any] = {}
            for v in match_verdicts:
                v_id = str(getattr(v, "requirement_id", ""))
                v_text = str(getattr(v, "requirement_text", "")).casefold()
                if v_id in req_id_to_skill:
                    skill_verdict_map[req_id_to_skill[v_id].casefold()] = v
                else:
                    for s in required_skills:
                        if s.casefold() == v_text or s.casefold() == v_id.casefold():
                            skill_verdict_map[s.casefold()] = v
                            break

            weighted_cov_sum = 0.0
            total_imp_weight = 0.0
            matched_skill_items = []
            missing_skill_items = []

            for s in required_skills:
                v = skill_verdict_map.get(s.casefold())
                if v is not None:
                    cov = float(getattr(v, "coverage_score", getattr(v, "coverage", 1.0 if _is_matched(v) else 0.0)) or 0.0)
                    imp = str(getattr(v, "importance", "critical") or "critical").lower()
                elif s in skills.matched_items:
                    cov = 1.0
                    imp = "critical"
                else:
                    cov = 0.0
                    imp = "important"

                w = IMPORTANCE_WEIGHTS.get(imp, 2.0)
                weighted_cov_sum += cov * w
                total_imp_weight += w

                if cov >= 0.35 or (v and _is_matched(v)) or s in skills.matched_items:
                    matched_skill_items.append(s)
                else:
                    missing_skill_items.append(s)

            skills_score = round((weighted_cov_sum / total_imp_weight) * 100.0, 2) if total_imp_weight > 0 else 0.0
            skills = ComponentScoreDetail(
                score=skills_score,
                matched_items=matched_skill_items,
                missing_items=missing_skill_items,
                explanation=f"Demonstrated {len(matched_skill_items)} of {len(required_skills)} required skills ({skills_score:.2f}% importance-weighted coverage).",
            )
        elif required_skills:
            skills = ComponentScoreDetail(
                score=round(min(100.0, (len(skills.matched_items) / len(required_skills)) * 100.0), 2),
                matched_items=skills.matched_items,
                missing_items=skills.missing_items,
                explanation=f"Matched {len(skills.matched_items)} of {len(required_skills)} required skills.",
            )

        # ── Responsibilities Component ─────────────────────────
        responsibility_verdicts = [
            v for v in (match_verdicts or [])
            if str(getattr(v, "requirement_id", "")).startswith("responsibility:")
            or getattr(getattr(v, "kind", None), "value", str(getattr(v, "kind", ""))) in {"responsibility", "responsibilities"}
        ]
        job_responsibilities = list(getattr(job, "responsibilities", None) or [])

        if responsibility_verdicts:
            weighted_resp_sum = 0.0
            total_resp_weight = 0.0
            matched_resp_items = []
            missing_resp_items = []

            for v in responsibility_verdicts:
                cov = float(getattr(v, "coverage_score", getattr(v, "coverage", 0.0)) or 0.0)
                if cov == 0.0:
                    if _is_matched(v):
                        cov = 1.0
                    elif any(kw in str(v.status).upper() or kw in str(getattr(v.status, "value", "")).upper() for kw in ("PARTIAL", "PARTIALLY_MATCHED")):
                        cov = 0.5
                imp = str(getattr(v, "importance", "important") or "important").lower()
                w = IMPORTANCE_WEIGHTS.get(imp, 2.0)
                weighted_resp_sum += cov * w
                total_resp_weight += w

                req_id = getattr(v, "requirement_id", "")
                if cov >= 0.35 or _is_matched(v):
                    matched_resp_items.append(req_id)
                else:
                    missing_resp_items.append(req_id)

            denom_weight = total_resp_weight if total_resp_weight > 0 else len(responsibility_verdicts)
            resp_score = round((weighted_resp_sum / denom_weight) * 100.0, 2) if denom_weight > 0 else 0.0
            responsibilities = ComponentScoreDetail(
                score=resp_score,
                matched_items=matched_resp_items,
                missing_items=missing_resp_items,
                explanation=f"Demonstrated {len(matched_resp_items)} of {len(responsibility_verdicts)} role responsibilities ({resp_score:.2f}% aggregate coverage).",
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
                score=0.0,
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
                score=0.0,
                matched_items=[],
                missing_items=[],
                explanation="No preferred skills configured (N/A).",
            )

        # ── Experience Duration Component (5% weight) ───────────────────────
        def _extract_item_months(item: dict[str, Any]) -> int:
            m = item.get("duration_months")
            if m is not None and isinstance(m, (int, float)) and m > 0:
                return int(m)
            start = item.get("start_date") or item.get("start")
            end = item.get("end_date") or item.get("end")
            if start:
                m_start = re.search(r"(\d{4})(?:[-/](\d{1,2}))?", str(start))
                m_end = re.search(r"(\d{4})(?:[-/](\d{1,2}))?", str(end)) if end else None
                if m_start:
                    y1 = int(m_start.group(1))
                    m1 = int(m_start.group(2)) if m_start.group(2) else 1
                    if m_end:
                        y2 = int(m_end.group(1))
                        m2 = int(m_end.group(2)) if m_end.group(2) else 12
                    else:
                        y2, m2 = y1 + 1, m1
                    calc_months = (y2 - y1) * 12 + (m2 - m1)
                    return max(1, calc_months)
            return 0

        candidate_months = sum(_extract_item_months(item) for item in (getattr(resume, "experience", None) or []))
        job_experience = getattr(job, "experience_requirements", None) or []
        job_min_months = 0
        job_max_months = 0
        for item in job_experience:
            if isinstance(item, dict):
                min_val = item.get("minimum_months") or 0
                max_val = item.get("maximum_months") or 0
                job_min_months = max(job_min_months, min_val)
                job_max_months = max(job_max_months, max_val)
            elif isinstance(item, str):
                m_range = re.search(r"(\d+)\s*[-–to]+\s*(\d+)\s+years?", item, re.I)
                m_min = re.search(r"(?:minimum|at\s+least|min)\s+(\d+)\s+years?", item, re.I) or re.search(r"(\d+)\+\s*years?", item, re.I) or re.search(r"(\d+)\s+years?", item, re.I)
                if m_range:
                    job_min_months = max(job_min_months, int(m_range.group(1)) * 12)
                    job_max_months = max(job_max_months, int(m_range.group(2)) * 12)
                elif m_min:
                    job_min_months = max(job_min_months, int(m_min.group(1)) * 12)
        min_exp = float(getattr(config, "min_experience_years", 0) or 0)
        required_months = max(job_min_months, round(min_exp * 12))

        if required_months > 0:
            duration_score = round(min(100.0, (candidate_months / required_months) * 100.0), 2)
            experience = ComponentScoreDetail(
                score=duration_score,
                matched_items=[f"{candidate_months} months"],
                missing_items=[] if candidate_months >= required_months else [f"{required_months - candidate_months} months"],
                explanation=f"Candidate experience is {candidate_months} months against {required_months} required months.",
            )
        elif job_experience and (job_max_months > 0 or any(item.get("display_value") for item in job_experience)):
            disp = job_experience[0].get("display_value") or f"0-{job_max_months // 12 or 1} years"
            experience = ComponentScoreDetail(
                score=100.0,
                matched_items=[f"{candidate_months} months"],
                missing_items=[],
                explanation=f"Candidate experience of {candidate_months} months satisfies entry-level requirement ({disp}).",
            )
        else:
            experience = ComponentScoreDetail(
                score=0.0,
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
        projects_score = self._projects_score(projects_list, job, resume=resume, match_verdicts=match_verdicts)
        education = self._education_component(resume, job, config, match_verdicts=match_verdicts)
        certifications = self._certifications_score(resume, job, config, match_verdicts=match_verdicts)
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

    FIELD_ALIASES: dict[str, str] = {
        "cs": "computer science",
        "cse": "computer science",
        "computer science and engineering": "computer science",
        "information technology": "computer science",
        "it": "computer science",
        "software engineering": "computer science",
        "data science": "computer science",
    }

    @classmethod
    def _extract_field(cls, text: str) -> str | None:
        if not text:
            return None
        t_cf = text.casefold()
        for kw in ("computer science", "information technology", "software engineering", "data science", "mechanical", "electrical", "civil", "business", "finance"):
            if kw in t_cf:
                return cls.FIELD_ALIASES.get(kw, kw)
        for alias, canonical in cls.FIELD_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", t_cf):
                return canonical
        return None

    @classmethod
    def _is_field_compatible(cls, req_field: str | None, cand_field: str | None, cand_full_text: str) -> bool:
        if not req_field:
            return True
        if cand_field and (cand_field.casefold() == req_field.casefold() or cls.FIELD_ALIASES.get(cand_field.casefold()) == req_field.casefold()):
            return True
        cand_cf = cand_full_text.casefold()
        if req_field.casefold() in cand_cf or any(alias in cand_cf for alias, can in cls.FIELD_ALIASES.items() if can.casefold() == req_field.casefold()):
            return True
        return False

    def _education_component(self, resume: Any, job: Any, config: Any, match_verdicts: list[Any] | None = None) -> ComponentScoreDetail:
        req_degree = getattr(config, "required_degree", None) or getattr(job, "required_degree", None)
        job_degrees = list(getattr(job, "degree_requirements", None) or getattr(job, "qualifications", None) or [])
        if req_degree:
            if isinstance(req_degree, str) and req_degree.strip() and req_degree.strip() not in job_degrees:
                job_degrees.insert(0, req_degree.strip())
            elif isinstance(req_degree, list):
                for d in req_degree:
                    if d and str(d).strip() and str(d).strip() not in job_degrees:
                        job_degrees.insert(0, str(d).strip())

        if not job_degrees:
            return ComponentScoreDetail(
                score=0.0,
                matched_items=[],
                missing_items=[],
                explanation="No specific education requirements configured (N/A).",
            )

        raw_edu = getattr(resume, "education", None) or []
        cand_edu_items: list[dict[str, str]] = []
        for item in raw_edu:
            if isinstance(item, dict):
                deg = item.get("degree") or item.get("title") or ""
                major = item.get("field") or item.get("major") or ""
                inst = item.get("institution") or item.get("school") or ""
                full_text = " ".join(part for part in [deg, major, inst] if part).strip()
            else:
                full_text = str(item).strip()
                deg = full_text
                major = ""
            if full_text:
                cand_edu_items.append({"degree": deg, "field": major, "full_text": full_text})

        if not cand_edu_items:
            return ComponentScoreDetail(
                score=0.0,
                matched_items=[],
                missing_items=job_degrees,
                explanation="No candidate education evidence found.",
            )

        matched_items: list[str] = []
        missing_items: list[str] = []
        graded_scores: list[float] = []

        for req in job_degrees:
            req_rank = self.degree_rank(req)
            req_field = self._extract_field(req)

            best_item_score = 0.0
            best_matched_text: str | None = None

            for cand in cand_edu_items:
                cand_rank = self.degree_rank(cand["full_text"])
                cand_field = self._extract_field(cand["full_text"])

                level_ok = (cand_rank >= req_rank) if req_rank > 0 else True
                field_ok = self._is_field_compatible(req_field, cand_field, cand["full_text"]) if req_field else True

                if level_ok and field_ok:
                    best_item_score = 100.0
                    best_matched_text = cand["full_text"]
                    break
                elif level_ok and not field_ok:
                    if best_item_score < 50.0:
                        best_item_score = 50.0
                        best_matched_text = f"{cand['full_text']} (Partial field match)"
                elif not level_ok and field_ok and cand_rank > 0:
                    if best_item_score < 50.0:
                        best_item_score = 50.0
                        best_matched_text = f"{cand['full_text']} (Lower degree level)"

            if best_item_score < 100.0 and match_verdicts:
                req_cf = req.casefold()
                for v in match_verdicts:
                    st = str(getattr(getattr(v, "status", None), "value", getattr(v, "status", ""))).upper()
                    req_id = str(getattr(v, "requirement_id", "")).casefold()
                    req_text = str(getattr(v, "requirement_text", getattr(v, "requirement_id", ""))).casefold()
                    reasoning = str(getattr(v, "reasoning", "")).casefold()
                    if st in {"MATCHED", "CONFIRMED", "AI_CONFIRMED"} and (req_id.startswith("degree:") or req_id.startswith("education:") or req_cf in req_text or req_cf in reasoning):
                        best_item_score = 100.0
                        best_matched_text = f"{req} (LLM Confirmed)"
                        break

            if best_item_score > 0.0:
                matched_items.append(best_matched_text or req)
                graded_scores.append(best_item_score)
            else:
                missing_items.append(req)
                graded_scores.append(0.0)

        overall_score = round(sum(graded_scores) / len(job_degrees), 2) if job_degrees else 0.0
        explanation = f"Matched {len(matched_items)} of {len(job_degrees)} required education qualifications (graded score: {overall_score:.2f}%)."

        return ComponentScoreDetail(
            score=overall_score,
            matched_items=matched_items,
            missing_items=missing_items,
            explanation=explanation,
        )

    def _projects_score(self, projects: list[dict[str, Any]], job: Any, resume: Any = None, match_verdicts: list[Any] | None = None) -> ComponentScoreDetail:
        # Non-project demonstrable concepts (protocols, soft skills, domain labels, meta notes)
        NON_PROJECT_PATTERNS = {
            "dns", "dhcp", "tcp/ip", "tcp", "ip", "udp", "vpn", "active directory",
            "communication", "teamwork", "soft skills", "willingness to learn", "problem-solving",
            "data engineering", "software engineering", "frontend development", "backend development",
            "full stack development", "sysops", "devops", "cloud engineering",
            "0-1 year", "1-3 years", "bachelor's degree", "master's degree",
        }

        def _is_project_demonstrable(kw: str) -> bool:
            cleaned = _clean_req_text(kw).casefold()
            if not cleaned or cleaned in NON_PROJECT_PATTERNS or cleaned in {t.casefold() for t in DESIGNATIONS}:
                return False
            if any(cleaned.startswith(p) for p in ("required skills should determine", "good-to-have skills are optional", "note:", "screening note", "business rule:", "rejection")):
                return False
            return True

        project_reqs = [k for k in list(getattr(job, "project_requirements", None) or []) if k and _is_project_demonstrable(k)]
        keywords_reqs = [k for k in list(getattr(job, "keywords", None) or []) if k and _is_project_demonstrable(k)]
        resps = list(getattr(job, "responsibilities", None) or [])

        # If job has no explicit project_requirements, no keywords, and no responsibilities, project score is N/A (0.0)
        if not project_reqs and not keywords_reqs and not resps:
            return ComponentScoreDetail(
                score=0.0,
                matched_items=[],
                missing_items=[],
                explanation="No specific project requirements configured (N/A).",
            )

        project_keywords = project_reqs or keywords_reqs
        if not project_keywords:
            skills_pool = getattr(job, "required_skills", None) or getattr(job, "skills", None) or []
            project_keywords = [k for k in skills_pool if k and _is_project_demonstrable(str(k))]

        if not project_keywords:
            return ComponentScoreDetail(
                score=0.0,
                matched_items=[],
                missing_items=[],
                explanation="No specific project requirements configured (N/A).",
            )

        has_candidate_projects = bool(projects or (getattr(resume, "experience", None) or []))
        if not has_candidate_projects:
            return ComponentScoreDetail(
                score=0.0,
                matched_items=[],
                missing_items=project_keywords,
                explanation="No candidate projects found.",
            )

        # Extract project evidence from candidate projects
        proj_terms: list[str] = []
        proj_blobs: list[str] = []
        for project in (projects or []):
            techs = project.get("technologies") or []
            proj_terms.extend(techs)
            name = project.get("name") or ""
            if name: proj_terms.append(name)
            for field_name in ("description", "deliverables", "highlights", "summary", "responsibilities", "outcomes", "details"):
                val = project.get(field_name)
                if isinstance(val, str) and val:
                    proj_blobs.append(val)
                    proj_terms.extend(re.findall(r"[A-Za-z0-9+#.]+", val))
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, str) and item:
                            proj_blobs.append(item)
                            proj_terms.extend(re.findall(r"[A-Za-z0-9+#.]+", item))

        # Extract experience/internship evidence
        exp_terms: list[str] = []
        exp_blobs: list[str] = []
        for exp in (getattr(resume, "experience", None) or []):
            techs = exp.get("technologies") or []
            exp_terms.extend(techs)
            title = exp.get("title") or exp.get("designation") or ""
            if title: exp_terms.append(title)
            for field_name in ("description", "responsibilities", "deliverables", "highlights"):
                val = exp.get(field_name)
                if isinstance(val, str) and val:
                    exp_blobs.append(val)
                    exp_terms.extend(re.findall(r"[A-Za-z0-9+#.]+", val))
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, str) and item:
                            exp_blobs.append(item)
                            exp_terms.extend(re.findall(r"[A-Za-z0-9+#.]+", item))

        proj_keys = self._keys(proj_terms)
        exp_keys = self._keys(exp_terms)
        proj_text_combined = " ".join([*proj_terms, *proj_blobs]).casefold()
        exp_text_combined = " ".join([*exp_terms, *exp_blobs]).casefold()

        # Canonicalize and deduplicate project competency groups
        seen_canonical: set[str] = set()
        canonical_competencies: list[str] = []
        for kw in project_keywords:
            cleaned = _clean_req_text(kw)
            if not cleaned or not _is_project_demonstrable(cleaned):
                continue
            canonical_alias = SKILL_ALIASES.get(cleaned.casefold(), cleaned)
            ckey = canonical_alias.casefold()
            if ckey not in seen_canonical:
                seen_canonical.add(ckey)
                canonical_competencies.append(cleaned)

        if not canonical_competencies:
            canonical_competencies = self._deduplicate([k for k in project_keywords if _is_project_demonstrable(k)])

        if not canonical_competencies:
            return ComponentScoreDetail(
                score=100.0,
                matched_items=[],
                missing_items=[],
                explanation="No specific project requirements configured (N/A).",
            )

        matched_display: list[str] = []
        missing_display: list[str] = []
        total_graded_score = 0.0
        audit_items: list[dict[str, Any]] = []

        for item in canonical_competencies:
            alternatives = [alt.strip() for alt in re.split(r"\s+(?:or|\/|\|)\s+|\s*,\s*or\s+", item, flags=re.IGNORECASE) if alt.strip()]
            if not alternatives: alternatives = [item.strip()]

            best_strength = 0.0
            best_matched_term = None
            best_source = "none"
            best_method = "unmatched"

            for alt in alternatives:
                # 1. Check direct project evidence (EXPLICIT_PROJECT = 1.00)
                proj_match = self._match_single_concept_candidate(alt, [*proj_terms, *proj_blobs], proj_keys)
                if proj_match or re.search(rf"(?:\b|_){re.escape(alt.casefold())}(?:\b|_)", proj_text_combined, re.I):
                    best_strength = 1.00
                    best_matched_term = proj_match or alt
                    best_source = "project"
                    best_method = "exact"
                    break

                # 2. Check internship/technical experience evidence (EXPLICIT_TECHNICAL_INTERNSHIP = 1.00)
                exp_match = self._match_single_concept_candidate(alt, [*exp_terms, *exp_blobs], exp_keys)
                if exp_match or re.search(rf"(?:\b|_){re.escape(alt.casefold())}(?:\b|_)", exp_text_combined, re.I):
                    if best_strength < 1.00:
                        best_strength = 1.00
                        best_matched_term = exp_match or alt
                        best_source = "experience"
                        best_method = "explicit_internship"
                        break

            # 3. Check LLM or verdict-confirmed matches (STRONG_SEMANTIC = 0.85 or EXPLICIT = 1.00)
            if best_strength < 1.00 and match_verdicts:
                item_cf = item.casefold()
                for v in match_verdicts:
                    status = str(getattr(getattr(v, "status", None), "value", getattr(v, "status", ""))).upper()
                    req_id = str(getattr(v, "requirement_id", "")).casefold()
                    req_text = str(getattr(v, "requirement_text", getattr(v, "requirement_id", ""))).casefold()
                    reasoning = str(getattr(v, "reasoning", "")).casefold()
                    if status == "MATCHED":
                        if req_id.startswith("project:") or req_id.startswith("project_competency:") or item_cf in req_text or item_cf in reasoning:
                            best_strength = 1.00
                            best_matched_term = item
                            best_source = "verdict_confirmed"
                            best_method = "llm_confirmed"
                            break

            if best_strength > 0.0:
                matched_display.append(best_matched_term or item)
                total_graded_score += best_strength
                verdict_str = "MATCHED" if best_strength >= 0.85 else "PARTIAL"
            else:
                missing_display.append(item)
                verdict_str = "UNMET"

            audit_items.append({
                "jd_text": item,
                "competency": item,
                "category": "PROJECT_DEMONSTRABLE",
                "evidence_source": best_source,
                "evidence_strength": "EXPLICIT_PROJECT" if best_strength == 1.0 and best_source == "project" else ("EXPLICIT_TECHNICAL_INTERNSHIP" if best_strength == 1.0 and best_source == "experience" else ("STRONG_SEMANTIC" if best_strength == 0.85 else "NONE")),
                "matching_method": best_method,
                "verdict": verdict_str,
                "score": best_strength,
            })

        score = round(min(100.0, (total_graded_score / len(canonical_competencies)) * 100.0), 2)
        if total_graded_score == 0.0 and not projects:
            exp_str = f"No candidate projects found (Matched 0 of {len(canonical_competencies)} project competencies)."
        else:
            exp_str = f"Matched {len(matched_display)} of {len(canonical_competencies)} project competencies (graded score: {score}%)."

        return ComponentScoreDetail(
            score=score,
            matched_items=matched_display,
            missing_items=missing_display,
            explanation=exp_str,
        )

    def _certifications_score(self, resume: Any, job: Any, config: Any, match_verdicts: list[Any] | None = None) -> ComponentScoreDetail:
        req_certs = list(getattr(config, "required_certifications", None) or [])
        if req_certs:
            raw_certs = getattr(resume, "certifications", None) or []
            cand_certs = [(c.get("name") or c.get("title") or "") if isinstance(c, dict) else str(c).strip() for c in raw_certs]
            cand_certs = [c for c in cand_certs if c]
            cert_detail = self._match(cand_certs, req_certs, "required certifications")
            if match_verdicts and cert_detail.missing_items:
                confirmed_certs = [
                    v for v in match_verdicts
                    if str(getattr(v, "requirement_id", "")).startswith("certification:")
                    and str(getattr(getattr(v, "status", None), "value", getattr(v, "status", None))).upper() == "MATCHED"
                ]
                if confirmed_certs:
                    new_matched = list(cert_detail.matched_items)
                    new_missing = []
                    for m in cert_detail.missing_items:
                        m_cf = m.casefold()
                        if any(m_cf in str(getattr(cc, "reasoning", "")).casefold() for cc in confirmed_certs):
                            new_matched.append(m)
                        else:
                            new_missing.append(m)
                    if len(new_matched) > len(cert_detail.matched_items):
                        return ComponentScoreDetail(
                            score=round(min(100.0, (len(new_matched) / len(req_certs)) * 100.0), 2),
                            matched_items=new_matched,
                            missing_items=new_missing,
                            explanation=f"Matched {len(new_matched)} of {len(req_certs)} required certifications.",
                        )
            return cert_detail
        return ComponentScoreDetail(
            score=0.0,
            matched_items=[],
            missing_items=[],
            explanation="No specific certification requirements configured (N/A).",
        )

    def _languages_score(self, resume: Any, config: Any) -> ComponentScoreDetail:
        req_langs = list(getattr(config, "required_languages", None) or [])
        if req_langs:
            return self._match(list(resume.languages or []), req_langs, "required languages")
        return ComponentScoreDetail(
            score=0.0,
            matched_items=[],
            missing_items=[],
            explanation="No specific language requirements configured (N/A).",
        )


    def _match_single_concept_candidate(self, alt: str, candidate: list[str], candidate_keys: set[str]) -> str | None:
        alt_clean = alt.strip()
        if not alt_clean:
            return None

        variants = list(dict.fromkeys([alt_clean, _clean_req_text(alt_clean)]))

        for a in variants:
            if not a:
                continue
            a_cf = a.casefold()

            # Check category requirement (e.g. PROGRAMMING_LANGUAGE, RELATIONAL_DATABASE, CLOUD_PLATFORMS)
            category_name = a.upper() if a.upper() in SKILL_CATEGORIES else (
                CATEGORY_REQUIREMENT_ALIASES.get(a_cf)
            )
            if category_name and category_name in SKILL_CATEGORIES:
                category_members = {m.casefold() for m in SKILL_CATEGORIES[category_name]}
                matched_member = next((k for k in candidate_keys if k in category_members), None)
                if matched_member:
                    return next((s for s in candidate if s.strip().casefold() == matched_member), matched_member.title())

            if a_cf in candidate_keys:
                return a

            canonical_alt = SKILL_ALIASES.get(a_cf)
            if canonical_alt and canonical_alt.casefold() in candidate_keys:
                return canonical_alt

            # Check all aliases mapping to this canonical target
            target_name = canonical_alt or a
            aliases_for_target = {k for k, v in SKILL_ALIASES.items() if v.casefold() == target_name.casefold()}
            matched_alias = next((k for k in candidate_keys if k in aliases_for_target), None)
            if matched_alias:
                return next((s for s in candidate if s.strip().casefold() == matched_alias), target_name)

            # Check if any alias appears in candidate text
            for cand_str in candidate:
                cand_str_lower = cand_str.casefold()
                if any(re.search(rf"\b{re.escape(al)}\b", cand_str_lower) for al in aliases_for_target if len(al) >= 3):
                    return target_name

            cand_matched = next(
                (
                    orig for orig in candidate
                    if (ck := orig.strip().casefold()) in candidate_keys and (
                        (can_ck := SKILL_ALIASES.get(ck)) and (
                            can_ck.casefold() == a_cf or
                            (canonical_alt and can_ck.casefold() == canonical_alt.casefold())
                        )
                    )
                ),
                None
            )
            if cand_matched:
                return cand_matched

            multi_match = self._match_multiword_concept(a, candidate)
            if multi_match:
                return a

        return None

    @classmethod
    def _deduplicate(cls, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if not item or not item.strip():
                continue
            cleaned = item.strip()
            key = SKILL_ALIASES.get(cleaned.casefold(), cleaned).casefold()
            if key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result

    def _match_groups(self, candidate: list[str], required_items: list[str], label: str) -> ComponentScoreDetail:
        """
        Match candidate items against required requirements.
        Supports AND conjunction groups formatted as "A and B" or "A, B, and C" where all items are required.
        Supports OR alternative groups formatted as "A / B / C" or "A or B or C" where matching any alternative satisfies the group.
        """
        candidate_keys = self._keys(candidate)
        matched_display: list[str] = []
        missing_display: list[str] = []
        satisfied_groups = 0

        # Clean and deduplicate requirement items while preserving group structure
        raw_items = self._deduplicate(required_items)
        if not raw_items:
            return ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=f"No {label} required (N/A).")

        for item in raw_items:
            # Check if item is a conjunction (AND compound requirement)
            is_conj = bool(re.search(r"\b(?:and|&)\b", item, re.I)) and not bool(re.search(r"\b(?:or|\/|\||such as|like|e\.g\.)\b", item, re.I))
            if is_conj:
                and_parts = [p.strip() for p in re.split(r"\s+(?:and|&)\s+|\s*,\s*and\s+", item, flags=re.I) if p.strip()]
                if len(and_parts) >= 2:
                    matched_all_parts = True
                    for part in and_parts:
                        part_matched = self._match_single_concept_candidate(part, candidate, candidate_keys)
                        if not part_matched:
                            matched_all_parts = False
                            break
                    if matched_all_parts:
                        satisfied_groups += 1
                        matched_display.append(item)
                    else:
                        missing_display.append(item)
                    continue

            # Otherwise evaluate OR alternatives / single concept
            such_parts = []
            such_match = re.search(r"\b(?:such\s+as|like|e\.g\.?|including)\s+(.+)$", item, re.I)
            if such_match:
                such_parts_raw = re.split(r"[,;/]|\s+or\s+", such_match.group(1).strip())
                such_parts = [p.strip() for p in such_parts_raw if p.strip()]

            raw_alts = re.split(r"\s*(?:\/|\|)\s*|\s+or\s+|\s*,\s*or\s*", item, flags=re.IGNORECASE)
            alternatives = list(dict.fromkeys([a.strip() for a in [*raw_alts, *such_parts, item] if a.strip()]))

            matched_alt = None
            for alt in alternatives:
                matched_alt = self._match_single_concept_candidate(alt, candidate, candidate_keys)
                if matched_alt:
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
        if not degree:
            return 0
        key = re.sub(r"[^a-z0-9]+", " ", degree.casefold()).strip()
        tokens = set(key.split())
        if any(w in tokens or w in key for w in ("doctorate", "phd", "doctor")):
            return 5
        if any(w in tokens or w in key for w in ("master", "masters", "mtech", "m tech", "me", "m e", "msc", "m sc", "ms", "m s", "mca", "mba")):
            return 4
        if any(w in tokens or w in key for w in ("bachelor", "bachelors", "btech", "b tech", "be", "b e", "bsc", "b sc", "bs", "b s", "bca", "bcom", "b com")):
            return 3
        if any(w in tokens or w in key for w in ("associate", "diploma")):
            return 2
        if "high school" in key or "secondary" in key:
            return 1
        return max((rank for name, rank in cls.DEGREE_RANKS.items() if name in key), default=0)

    @classmethod
    def _education_score(cls, candidate: list[str], required: str | None) -> float:
        if not required: return 100.0
        if not candidate: return 0.0
        required_rank = cls.degree_rank(required)
        candidate_rank = max((cls.degree_rank(value) for value in candidate), default=0)
        if required_rank and candidate_rank >= required_rank: return 100.0
        if any(value.casefold() == required.casefold() for value in candidate): return 100.0
        return 50.0
