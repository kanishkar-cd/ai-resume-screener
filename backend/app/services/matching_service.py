from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.schemas.matching import (
    CandidateMatchingProfile, Evidence, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict,
    NormalizedMatchResult, Requirement, RequirementKind, ResponsibilityMatchDetail,
)
from app.services.pipeline.canonical_dictionaries import (
    CERTIFICATION_ALIASES, DEGREE_ALIASES, LANGUAGE_ALIASES, SKILL_ALIASES, TITLE_ALIASES,
)
from app.services.scoring.component_scoring_service import ComponentScoringService

logger = structlog.get_logger(__name__)
_TOKEN = re.compile(r"[a-z0-9+#.]+")
_CONTEXTUAL = {
    RequirementKind.RESPONSIBILITY,
}


def _key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN.findall(value.casefold()) if len(token) > 1}


class RequirementBuilder:
    """Convert the normalized JD into stable requirement objects."""

    @staticmethod
    def build(job: Any, config: Any = None) -> list[Requirement]:
        rows: list[tuple[RequirementKind, str, bool, bool]] = []
        mandatory = {_key(value) for value in (getattr(config, "mandatory_skills", None) or [])}
        preferred = {_key(value) for value in (getattr(job, "preferred_skills", None) or [])}
        req_skills = getattr(job, "required_skills", None) or getattr(job, "skills", None) or []
        for value in req_skills:
            key = _key(value)
            rows.append((RequirementKind.SKILL, value, key not in preferred, key in mandatory))
        for value in getattr(job, "degree_requirements", None) or []:
            rows.append((RequirementKind.DEGREE, value, True, False))
        for value in [
            *(getattr(job, "certifications", None) or []),
            *(getattr(config, "required_certifications", None) or []),
        ]:
            rows.append((RequirementKind.CERTIFICATION, value, True, False))
        for value in getattr(config, "required_languages", None) or []:
            rows.append((RequirementKind.LANGUAGE, value, True, False))
        for value in getattr(job, "responsibilities", None) or []:
            rows.append((RequirementKind.RESPONSIBILITY, value, True, False))

        result: list[Requirement] = []
        seen: set[tuple[RequirementKind, str]] = set()
        counters: dict[RequirementKind, int] = {}
        for kind, text, required, hard in rows:
            identity = (kind, _key(text))
            if not text.strip() or identity in seen:
                continue
            seen.add(identity)
            counters[kind] = counters.get(kind, 0) + 1
            result.append(Requirement(
                requirement_id=f"{kind.value}:{counters[kind]}", kind=kind,
                text=text.strip(), canonical_value=text.strip(), required=required,
                hard_constraint=hard,
            ))
        return result


class EvidenceBuilder:
    """Convert the normalized Resume into stable evidence objects."""

    @staticmethod
    def _projects(resume_or_extracted: Any, fallback_extracted: Any = None) -> list[dict[str, Any]]:
        raw_projects = getattr(resume_or_extracted, "projects", None) or getattr(fallback_extracted, "projects", None) or []
        projects: list[dict[str, Any]] = []
        for p in raw_projects:
            if isinstance(p, dict):
                projects.append(dict(p))
            else:
                p_obj = getattr(p, "__dict__", {}) or {}
                projects.append({
                    "name": getattr(p, "name", None) or p_obj.get("name"),
                    "description": getattr(p, "description", None) or p_obj.get("description"),
                    "technologies": getattr(p, "technologies", None) or p_obj.get("technologies") or [],
                })
        if len(projects) <= 1:
            return projects
        descriptions = (projects[0].get("description") or "").splitlines()
        descriptions = [value.strip() for value in descriptions if value.strip()]
        if len(descriptions) == len(projects) and all(
            not project.get("description") for project in projects[1:]
        ):
            for project, description in zip(projects, descriptions, strict=True):
                project["description"] = description
        return projects

    @staticmethod
    def build(resume_or_extracted: Any, fallback_extracted: Any = None) -> list[Evidence]:
        result: list[Evidence] = []
        for index, project in enumerate(EvidenceBuilder._projects(resume_or_extracted, fallback_extracted), start=1):
            name = project.get("name") or ""
            description = project.get("description") or ""
            technologies = project.get("technologies") or []
            text = " ".join(value for value in [name, description, *technologies] if value).strip()
            if text:
                result.append(Evidence(
                    evidence_id=f"project:{index}", kind="project", text=text,
                    canonical_terms=list(technologies),
                ))
        exp_list = getattr(resume_or_extracted, "experience", None) or getattr(fallback_extracted, "experience", None) or []
        for index, item in enumerate(exp_list, start=1):
            obj = item if isinstance(item, dict) else getattr(item, "__dict__", {}) or {}
            title = obj.get("job_title") or obj.get("title") or obj.get("designation") or ""
            company = obj.get("company") or ""
            description = obj.get("description") or ""
            responsibilities = obj.get("responsibilities") or []
            text = " ".join(value for value in [
                title, company, description, *responsibilities,
            ] if value).strip()
            if text:
                result.append(Evidence(
                    evidence_id=f"experience:{index}", kind="experience", text=text,
                    canonical_terms=[v for v in [title, company] if v],
                ))
        skills = [str(s).strip() for s in (getattr(resume_or_extracted, "skills", None) or getattr(fallback_extracted, "skills", None) or []) if str(s).strip()]
        if skills:
            result.append(Evidence(
                evidence_id="skills:1", kind="skills", text=", ".join(skills),
                canonical_terms=list(skills),
            ))
        for index, item in enumerate(getattr(resume_or_extracted, "education", None) or getattr(fallback_extracted, "education", None) or [], start=1):
            obj = item if isinstance(item, dict) else getattr(item, "__dict__", {}) or {}
            degree = obj.get("degree") or ""
            field = obj.get("field_of_study") or ""
            inst = obj.get("institution") or ""
            text = " ".join(v for v in [degree, field, inst] if v).strip()
            if text:
                result.append(Evidence(
                    evidence_id=f"education:{index}", kind="education", text=text,
                    canonical_terms=[v for v in [degree, field] if v],
                ))
        certs = [str(c).strip() for c in (getattr(resume_or_extracted, "certifications", None) or getattr(fallback_extracted, "certifications", None) or []) if str(c).strip()]
        for index, cert in enumerate(certs, start=1):
            result.append(Evidence(
                evidence_id=f"certification:{index}", kind="certification", text=cert,
                canonical_terms=[cert],
            ))
        langs = [str(l).strip() for l in (getattr(resume_or_extracted, "languages", None) or getattr(fallback_extracted, "languages", None) or []) if str(l).strip()]
        if langs:
            result.append(Evidence(
                evidence_id="languages:1", kind="languages", text=", ".join(langs),
                canonical_terms=list(langs),
            ))
        return result


class DeterministicRequirementMatcher:
    @staticmethod
    def _canonical(value: str, aliases: dict[str, str]) -> tuple[str, MatchMethod]:
        key = _key(value)
        canonical = aliases.get(key)
        if not canonical:
            return key, MatchMethod.EXACT
        canonical_key = _key(canonical)
        return canonical_key, MatchMethod.EXACT if key == canonical_key else MatchMethod.ALIAS

    def match(self, requirement: Requirement, resume: Any, evidence: list[Evidence]) -> MatchVerdict:
        if requirement.kind in _CONTEXTUAL:
            required_key = _key(requirement.canonical_value or requirement.text)
            for item in evidence:
                canonical = {_key(value) for value in item.canonical_terms}
                text_key = _key(item.text)
                if required_key in canonical or required_key in text_key or any(required_key in _key(cand) for cand in item.canonical_terms):
                    return MatchVerdict(
                        requirement_id=requirement.requirement_id,
                        status=MatchStatus.MATCHED, confidence=1.0,
                        evidence_ids=[item.evidence_id],
                        reasoning="Contextual evidence contains requirement.",
                        method=MatchMethod.EXACT,
                    )
            return MatchVerdict(
                requirement_id=requirement.requirement_id, status=MatchStatus.UNRESOLVED,
                confidence=0, reasoning="Contextual requirement requires evidence review.",
            )
        aliases: dict[str, str]
        candidates: list[str]
        if requirement.kind == RequirementKind.SKILL:
            aliases, candidates = SKILL_ALIASES, list(getattr(resume, "skills", None) or [])
        elif requirement.kind == RequirementKind.DEGREE:
            aliases = DEGREE_ALIASES
            candidates = [
                (item.get("degree") if isinstance(item, dict) else getattr(item, "degree", None))
                for item in (getattr(resume, "education", None) or [])
                if (item.get("degree") if isinstance(item, dict) else getattr(item, "degree", None))
            ]
        elif requirement.kind == RequirementKind.CERTIFICATION:
            aliases, candidates = CERTIFICATION_ALIASES, list(getattr(resume, "certifications", None) or [])
        elif requirement.kind == RequirementKind.LANGUAGE:
            aliases, candidates = LANGUAGE_ALIASES, list(getattr(resume, "languages", None) or [])
        else:
            aliases, candidates = {}, []

        required_key, required_method = self._canonical(requirement.canonical_value or requirement.text, aliases)
        for candidate in candidates:
            candidate_key, candidate_method = self._canonical(candidate, aliases)
            if candidate_key == required_key:
                method = MatchMethod.ALIAS if MatchMethod.ALIAS in {required_method, candidate_method} else MatchMethod.EXACT
                return MatchVerdict(
                    requirement_id=requirement.requirement_id, status=MatchStatus.MATCHED,
                    confidence=1, evidence_ids=[], reasoning="Canonical values match.", method=method,
                )
        if requirement.kind == RequirementKind.DEGREE:
            required_rank = ComponentScoringService.degree_rank(requirement.text)
            if required_rank and any(ComponentScoringService.degree_rank(value) >= required_rank for value in candidates):
                return MatchVerdict(
                    requirement_id=requirement.requirement_id, status=MatchStatus.MATCHED,
                    confidence=1, reasoning="Degree taxonomy level satisfies requirement.",
                    method=MatchMethod.TAXONOMY,
                )
        return MatchVerdict(
            requirement_id=requirement.requirement_id, status=MatchStatus.NO_MATCH,
            confidence=1, reasoning="No deterministic canonical match.",
        )


class EvidencePrefilter:
    def __init__(self, threshold: float, limit: int) -> None:
        self.threshold, self.limit = threshold, limit

    def select(self, requirement: Requirement, evidence: list[Evidence]) -> list[Evidence]:
        if not evidence:
            return []
        required = _tokens(requirement.text)
        scored = []
        for item in evidence:
            overlap = len(required & _tokens(item.text)) / len(required) if required else 0.0
            scored.append((overlap, item.evidence_id, item))
        scored.sort(key=lambda row: (-row[0], row[1]))
        passing = [row[2] for row in scored if row[0] >= self.threshold]
        if passing:
            return passing[: self.limit]
        return [row[2] for row in scored[: self.limit]]


class GroqMatchEvaluator:
    _cache: OrderedDict[str, list[MatchVerdict]] = OrderedDict()
    _client: httpx.AsyncClient | None = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @classmethod
    def _get_client(cls, timeout: float) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(timeout=timeout)
        return cls._client

    @property
    def enabled(self) -> bool:
        return bool(self.settings.ENABLE_HYBRID_MATCHING and self.settings.GROQ_API_KEY)

    async def evaluate(
        self, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
    ) -> list[MatchVerdict]:
        if not self.enabled or not requirements or not evidence:
            return []
        digest = hashlib.sha256(json.dumps({
            "requirements": [r.model_dump(mode="json") for r in requirements],
            "evidence": [e.model_dump(mode="json") for e in evidence],
            "model": self.settings.GROQ_MODEL,
            "threshold": self.settings.HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD,
            "allowed_evidence": {key: sorted(value) for key, value in (allowed_evidence or {}).items()},
        }, sort_keys=True).encode()).hexdigest()
        if digest in self._cache:
            self._cache.move_to_end(digest)
            return [verdict.model_copy(deep=True) for verdict in self._cache[digest]]

        payload = self._payload(requirements, evidence)
        parsed: LLMVerdictBatch | None = None
        client = self._get_client(self.settings.AI_EXTRACTION_TIMEOUT_SECONDS)
        for attempt in range(2):
            try:
                response = await client.post(
                    f"{self.settings.GROQ_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.GROQ_API_KEY}"}, json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                parsed = LLMVerdictBatch.model_validate(json.loads(content) if isinstance(content, str) else content)
                break
            except Exception as exc:
                logger.warning("hybrid_match_llm_attempt_failed", attempt=attempt + 1, error_type=type(exc).__name__)
        if parsed is None:
            return []
        validated = self._validate(parsed, requirements, evidence, allowed_evidence)
        self._cache[digest] = validated
        self._cache.move_to_end(digest)
        while len(self._cache) > self.settings.HYBRID_MATCHING_CACHE_SIZE:
            self._cache.popitem(last=False)
        return [verdict.model_copy(deep=True) for verdict in validated]

    def _validate(
        self, batch: LLMVerdictBatch, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
    ) -> list[MatchVerdict]:
        requirement_ids = {item.requirement_id for item in requirements}
        evidence_ids = {item.evidence_id for item in evidence}
        threshold = self.settings.HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD
        result: list[MatchVerdict] = []
        seen: set[str] = set()
        for item in batch.verdicts:
            allowed = (allowed_evidence or {}).get(item.requirement_id, evidence_ids)
            valid_evidence = bool(item.evidence_ids) and all(
                value in evidence_ids and value in allowed for value in item.evidence_ids
            )
            if item.requirement_id not in requirement_ids or item.requirement_id in seen:
                continue
            seen.add(item.requirement_id)
            confirmed = item.status == MatchStatus.MATCHED and item.confidence >= threshold and valid_evidence
            accepted_no_match = item.status == MatchStatus.NO_MATCH and valid_evidence
            status = MatchStatus.MATCHED if confirmed else MatchStatus.NO_MATCH if accepted_no_match else MatchStatus.UNRESOLVED
            method = MatchMethod.LLM_CONFIRMED if confirmed else MatchMethod.LLM_REJECTED if accepted_no_match else MatchMethod.LLM_UNRESOLVED
            reasoning = item.reasoning if (confirmed or accepted_no_match) else (item.reasoning or "LLM verdict unresolved by confidence or evidence validation.")
            result.append(MatchVerdict(
                requirement_id=item.requirement_id,
                status=status,
                confidence=item.confidence if (confirmed or accepted_no_match) else 0.0,
                evidence_ids=item.evidence_ids if valid_evidence else [],
                reasoning=reasoning,
                method=method,
            ))
        return result

    def _payload(self, requirements: list[Requirement], evidence: list[Evidence]) -> dict[str, Any]:
        content = json.dumps({
            "requirements": [item.model_dump(mode="json") for item in requirements],
            "evidence": [item.model_dump(mode="json") for item in evidence],
        })
        return {
            "model": self.settings.GROQ_MODEL, "temperature": 0,
            "messages": [
                {"role": "system", "content": (
                    "Evaluate supplied Job Description requirements against supplied candidate resume evidence. "
                    "Determine status (MATCHED, NO_MATCH, or UNRESOLVED), confidence (0.0 to 1.0), and reasoning. "
                    "Never infer missing facts or invent evidence. "
                    "Cite only supplied evidence_ids that directly support your decision. "
                    "Return one JSON object with exactly this shape: "
                    "{\"verdicts\":[{\"requirement_id\":\"string\",\"status\":\"MATCHED|NO_MATCH|UNRESOLVED\","
                    "\"confidence\":0.0,\"evidence_ids\":[\"string\"],\"reasoning\":\"string\"}]}. "
                    "Do not add extra fields or markdown."
                )},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
        }


class HybridMatchingService:
    def __init__(self, settings: Settings | None = None, evaluator: GroqMatchEvaluator | None = None) -> None:
        self.settings = settings or get_settings()
        self.evaluator = evaluator or GroqMatchEvaluator(self.settings)
        self.matcher = DeterministicRequirementMatcher()

    async def match(
        self, job: Any, resume: Any, extracted: Any = None, config: Any = None,
    ) -> tuple[NormalizedMatchResult, list[MatchVerdict]]:
        target_resume = resume if resume is not None else extracted
        requirements = RequirementBuilder.build(job, config)
        evidence = EvidenceBuilder.build(target_resume, fallback_extracted=extracted)

        candidate_skills = list(getattr(target_resume, "skills", None) or [])
        candidate_projects = [
            p if isinstance(p, dict) else getattr(p, "__dict__", {}) or {}
            for p in (getattr(target_resume, "projects", None) or [])
        ]
        candidate_experience = [
            e if isinstance(e, dict) else getattr(e, "__dict__", {}) or {}
            for e in (getattr(target_resume, "experience", None) or [])
        ]
        candidate_education = [
            item if isinstance(item, dict) else getattr(item, "__dict__", {}) or {}
            for item in (getattr(target_resume, "education", None) or [])
        ]
        total_exp_months = int(getattr(target_resume, "total_experience_months", 0) or 0)
        cand_level = str(getattr(target_resume, "candidate_level", "FRESHER") or "FRESHER")

        # 1. Build Candidate Skill Pool (deduplicated canonical skill keys)
        skill_evidence_strings: set[str] = set()
        for s in candidate_skills:
            if s and str(s).strip():
                skill_evidence_strings.add(str(s).strip())
        for p in candidate_projects:
            techs = p.get("technologies") or []
            for t in techs:
                if t and str(t).strip():
                    skill_evidence_strings.add(str(t).strip())
        for exp in candidate_experience:
            resps = exp.get("responsibilities") or []
            for r in resps:
                if r and str(r).strip():
                    skill_evidence_strings.add(str(r).strip())

        candidate_skill_keys: set[str] = set()
        for s_str in skill_evidence_strings:
            key = _key(s_str)
            canonical = SKILL_ALIASES.get(key, key)
            candidate_skill_keys.add(_key(canonical))

        # 2. Required Skills Matching
        job_req_skills = list(getattr(job, "required_skills", None) or getattr(job, "skills", None) or [])
        matched_req: list[str] = []
        missing_req: list[str] = []
        for req_skill in job_req_skills:
            if not str(req_skill).strip():
                continue
            r_key = _key(req_skill)
            r_canonical = _key(SKILL_ALIASES.get(r_key, r_key))
            if r_key in candidate_skill_keys or r_canonical in candidate_skill_keys:
                if req_skill not in matched_req:
                    matched_req.append(req_skill)
            else:
                matched_token = any(r_key in _key(cand_s) or _key(cand_s) in r_key for cand_s in skill_evidence_strings)
                if matched_token:
                    if req_skill not in matched_req:
                        matched_req.append(req_skill)
                else:
                    if req_skill not in missing_req:
                        missing_req.append(req_skill)

        req_score = round(min(100.0, (len(matched_req) / len(job_req_skills)) * 100.0), 2) if job_req_skills else 100.0

        # 3. Preferred Skills Matching
        job_pref_skills = list(getattr(job, "preferred_skills", None) or [])
        matched_pref: list[str] = []
        missing_pref: list[str] = []
        for pref_skill in job_pref_skills:
            if not str(pref_skill).strip():
                continue
            p_key = _key(pref_skill)
            p_canonical = _key(SKILL_ALIASES.get(p_key, p_key))
            if p_key in candidate_skill_keys or p_canonical in candidate_skill_keys:
                if pref_skill not in matched_pref:
                    matched_pref.append(pref_skill)
            else:
                matched_token = any(p_key in _key(cand_s) or _key(cand_s) in p_key for cand_s in skill_evidence_strings)
                if matched_token:
                    if pref_skill not in matched_pref:
                        matched_pref.append(pref_skill)
                else:
                    if pref_skill not in missing_pref:
                        missing_pref.append(pref_skill)

        pref_score = round(min(100.0, (len(matched_pref) / len(job_pref_skills)) * 100.0), 2) if job_pref_skills else 100.0

        # 4. Responsibilities Matching
        job_resps = list(getattr(job, "responsibilities", None) or [])
        resp_details: list[ResponsibilityMatchDetail] = []
        deterministic_verdicts = [self.matcher.match(item, target_resume, evidence) for item in requirements]
        prefilter = EvidencePrefilter(
            self.settings.HYBRID_MATCHING_KEYWORD_OVERLAP_THRESHOLD,
            self.settings.HYBRID_MATCHING_MAX_EVIDENCE_PER_REQUIREMENT,
        )

        unresolved_reqs: list[Requirement] = []
        supplied_evidence: dict[str, Evidence] = {}
        allowed_ev_map: dict[str, set[str]] = {}

        evaluator_enabled = bool(getattr(self.evaluator, "enabled", True))
        for verdict in deterministic_verdicts:
            if verdict.requirement_id.startswith("responsibility:"):
                req_item = next((r for r in requirements if r.requirement_id == verdict.requirement_id), None)
                if req_item:
                    if verdict.status == MatchStatus.MATCHED:
                        resp_details.append(ResponsibilityMatchDetail(
                            responsibility=req_item.text, status=MatchStatus.MATCHED,
                            confidence=verdict.confidence, evidence_ids=verdict.evidence_ids,
                            reasoning=verdict.reasoning, method=verdict.method,
                        ))
                    else:
                        selected = prefilter.select(req_item, evidence)
                        if selected and evaluator_enabled:
                            unresolved_reqs.append(req_item)
                            supplied_evidence.update((item.evidence_id, item) for item in selected)
                            allowed_ev_map[req_item.requirement_id] = {item.evidence_id for item in selected}
                        else:
                            resp_details.append(ResponsibilityMatchDetail(
                                responsibility=req_item.text, status=MatchStatus.NO_MATCH,
                                confidence=1.0, reasoning="No keyword or contextual match found.",
                                method=MatchMethod.EXACT,
                            ))

        if unresolved_reqs and evaluator_enabled:
            llm_verdicts = await self.evaluator.evaluate(unresolved_reqs, list(supplied_evidence.values()), allowed_ev_map)
            llm_by_id = {v.requirement_id: v for v in llm_verdicts}
            for req in unresolved_reqs:
                lv = llm_by_id.get(req.requirement_id)
                if lv:
                    resp_details.append(ResponsibilityMatchDetail(
                        responsibility=req.text, status=lv.status, confidence=lv.confidence,
                        evidence_ids=lv.evidence_ids, reasoning=lv.reasoning, method=lv.method,
                    ))
                else:
                    resp_details.append(ResponsibilityMatchDetail(
                        responsibility=req.text, status=MatchStatus.NO_MATCH, confidence=1.0,
                        reasoning="LLM evaluation unresolved.", method=MatchMethod.LLM_REJECTED,
                    ))

        matched_resp_count = sum(1 for rd in resp_details if rd.status == MatchStatus.MATCHED)
        resp_score = round(min(100.0, (matched_resp_count / len(job_resps)) * 100.0), 2) if job_resps else 100.0

        # 5. Job Title Score
        jd_title = getattr(job, "job_title", None)
        cand_titles = list(getattr(target_resume, "job_titles", None) or [])
        for exp in candidate_experience:
            t = exp.get("job_title") or exp.get("title")
            if t and t not in cand_titles:
                cand_titles.append(t)

        if not jd_title:
            job_title_score = 100.0
        else:
            jd_key = _key(jd_title)
            jd_canonical = _key(TITLE_ALIASES.get(jd_key, jd_key))
            title_matched = False
            token_matched = False
            for ct in cand_titles:
                c_key = _key(ct)
                c_canonical = _key(TITLE_ALIASES.get(c_key, c_key))
                if c_key == jd_key or c_canonical == jd_canonical:
                    title_matched = True
                    break
                elif any(word in c_key for word in _tokens(jd_title)):
                    token_matched = True

            job_title_score = 100.0 if title_matched else (75.0 if token_matched else 40.0)

        # 6. Candidate Level & Relevant Experience Score
        req_exp_items = list(getattr(job, "experience_requirements", None) or [])
        min_months = 0
        for item in req_exp_items:
            m = item.get("minimum_months") if isinstance(item, dict) else getattr(item, "minimum_months", 0)
            if isinstance(m, int) and m > min_months:
                min_months = m

        jd_required_level = "EXPERIENCED" if min_months > 12 else "FRESHER"

        if cand_level == "FRESHER":
            relevant_exp_score = None
        else:
            eff_req = max(min_months, 12)
            relevant_exp_score = round(min(100.0, (total_exp_months / eff_req) * 100.0), 2)

        # Step 4: Calculate Final Match Score (0–100)
        if cand_level == "FRESHER":
            raw_final = (
                (req_score * 0.45)
                + (resp_score * 0.35)
                + (pref_score * 0.10)
                + (job_title_score * 0.10)
            )
        else:
            rel_exp = relevant_exp_score if relevant_exp_score is not None else 0.0
            raw_final = (
                (req_score * 0.40)
                + (resp_score * 0.35)
                + (pref_score * 0.10)
                + (job_title_score * 0.05)
                + (rel_exp * 0.10)
            )

        final_match_score = round(max(0.0, min(100.0, raw_final)), 2)

        profile = CandidateMatchingProfile(
            candidate_name=getattr(target_resume, "candidate_name", None),
            email=getattr(target_resume, "email", None),
            phone=getattr(target_resume, "phone", None),
            resume_job_title=cand_titles[0] if cand_titles else None,
            jd_job_title=jd_title,
            total_experience_months=total_exp_months,
            candidate_level=cand_level,
            jd_required_level=jd_required_level,
            education=candidate_education,
        )

        result = NormalizedMatchResult(
            profile=profile,
            required_skills_score=req_score,
            responsibility_score=resp_score,
            preferred_skills_score=pref_score,
            job_title_score=job_title_score,
            relevant_experience_score=relevant_exp_score,
            final_match_score=final_match_score,
            matched_required_skills=matched_req,
            missing_required_skills=missing_req,
            matched_preferred_skills=matched_pref,
            missing_preferred_skills=missing_pref,
            responsibility_details=resp_details,
            short_relevance_explanation=f"Matched {len(matched_req)}/{len(job_req_skills or matched_req)} required skills.",
        )

        llm_by_id = {rd.responsibility: rd for rd in resp_details}
        fused_verdicts: list[MatchVerdict] = []
        for v in deterministic_verdicts:
            req_item = next((r for r in requirements if r.requirement_id == v.requirement_id), None)
            if req_item and req_item.text in llm_by_id:
                rd = llm_by_id[req_item.text]
                fused_verdicts.append(MatchVerdict(
                    requirement_id=v.requirement_id,
                    status=rd.status,
                    confidence=rd.confidence,
                    evidence_ids=rd.evidence_ids,
                    reasoning=rd.reasoning,
                    method=rd.method,
                ))
            else:
                fused_verdicts.append(v)

        return result, fused_verdicts
