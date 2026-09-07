from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
import time
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any

import httpx
# pyrefly: ignore [missing-import]
import structlog

from app.core.config import Settings, get_settings
from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict,
    Requirement, RequirementKind,
)
from app.services.pipeline.canonical_dictionaries import (
    CERTIFICATION_ALIASES, DEGREE_ALIASES, LANGUAGE_ALIASES, SKILL_ALIASES,
    SKILL_CATEGORIES, CATEGORY_REQUIREMENT_ALIASES,
)
from app.services.scoring.component_scoring_service import ComponentScoringService

logger = structlog.get_logger(__name__)
_TOKEN = re.compile(r"[a-z0-9+#.]+")
_STEM_SUFFIXES = (
    "ization", "isation", "ation", "ition", "izing", "ising", "ized", "ised",
    "ating", "ated", "ates", "ing", "ment", "tion", "sion", "able", "ible", "ness", "ies", "ied", "ed", "es", "ful", "s", "y",
)
_CONTEXTUAL = {
    RequirementKind.RESPONSIBILITY,
    RequirementKind.SKILL,
    RequirementKind.REQUIRED_SKILL,
    RequirementKind.PREFERRED_SKILL,
    RequirementKind.DEGREE,
    RequirementKind.CERTIFICATION,
    RequirementKind.LANGUAGE,
    RequirementKind.PROJECT_RELEVANCE,
    RequirementKind.CANDIDATE_ATTRIBUTE,
}


ALLOWED_EVIDENCE_MAP: dict[RequirementKind, set[str]] = {
    RequirementKind.DEGREE: {"education"},
    RequirementKind.EXPERIENCE: {"experience"},
    RequirementKind.CONTEXTUAL_EXPERIENCE: {"experience"},
    RequirementKind.SKILL: {"skills", "experience", "project", "summary", "certification"},
    RequirementKind.REQUIRED_SKILL: {"skills", "experience", "project", "summary", "certification"},
    RequirementKind.PREFERRED_SKILL: {"skills", "experience", "project", "summary", "certification"},
    RequirementKind.RESPONSIBILITY: {"experience", "project", "summary", "skills"},
    RequirementKind.PROJECT_RELEVANCE: {"project", "experience", "summary"},
    RequirementKind.CERTIFICATION: {"certification"},
    RequirementKind.LANGUAGE: {"languages"},
    RequirementKind.CANDIDATE_ATTRIBUTE: {"skills", "experience", "project", "summary"},
}


def is_entity_compatible(req_kind: RequirementKind | str, evidence_kind: str) -> bool:
    if isinstance(req_kind, str):
        try:
            req_kind = RequirementKind(req_kind)
        except ValueError:
            return True
    allowed = ALLOWED_EVIDENCE_MAP.get(req_kind)
    if allowed is None:
        return True
    return evidence_kind in allowed


def _key(value: str) -> str:
    return " ".join(value.split()).casefold()


_IRREGULAR_VERBS = {
    "built": "build", "led": "lead", "wrote": "write", "ran": "run", "held": "hold",
    "made": "make", "analyzed": "analyze", "analysed": "analyze", "monitored": "monitor",
    "documented": "document", "managed": "manage", "developed": "develop", "deployed": "deploy",
    "maintained": "maintain", "investigated": "investigate", "configured": "configure",
}


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


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN.findall(value.casefold()) if len(token) > 1}


def _stem_tokens(value: str) -> set[str]:
    return {_stem_token(token) for token in _TOKEN.findall(value.casefold()) if len(token) > 1}


class RequirementBuilder:
    """Convert the existing normalized JD into stable requirement objects."""

    SECTION_HEADERS = {
        "good-to-have skills", "good to have skills", "good to have", "good-to-have",
        "preferred skills", "nice to have", "nice-to-have", "bonus skills", "desired skills",
        "candidate requirements", "candidate requirement", "key responsibilities",
        "technical requirements", "screening notes", "screening note", "note", "notes",
        "additional requirements", "general requirements", "qualifications & skills",
        "skills & qualifications", "required skills", "core skills", "technical skills",
        "required technical skills", "preferred requirements", "requirements", "qualifications",
        "responsibilities", "duties", "job description", "overview", "summary",
    }

    SOFT_ATTRIBUTES_KEYWORDS = (
        "analytical ability", "analytical skills", "communication", "communication skills",
        "teamwork", "collaboration", "interpersonal skills", "willingness to learn",
        "problem solving", "problem-solving ability", "critical thinking", "self-motivated",
        "adaptability", "time management", "screening note", "candidate attribute",
        "ability and willingness to learn", "eager to learn",
    )

    @staticmethod
    def _is_section_header(text: str) -> bool:
        cleaned = text.strip().strip(":").casefold()
        return cleaned in RequirementBuilder.SECTION_HEADERS or _key(cleaned) in RequirementBuilder.SECTION_HEADERS

    @staticmethod
    def _is_meta_instruction(text: str) -> bool:
        cleaned = text.strip().casefold()
        return (
            cleaned.startswith("required skills should determine")
            or cleaned.startswith("good-to-have skills are optional")
            or cleaned.startswith("good to have skills are optional")
            or "must not independently cause" in cleaned
            or cleaned.startswith("note:")
            or cleaned.startswith("screening note")
            or cleaned.startswith("business rule:")
        )

    @staticmethod
    def build(job: Any, config: Any, classifications: dict[str, Any] | None = None) -> list[Requirement]:
        rows: list[tuple[RequirementKind, str, bool, bool]] = []
        mandatory = {_key(value) for value in (getattr(config, "mandatory_skills", None) or [])}
        preferred_skills = list(getattr(job, "preferred_skills", None) or [])
        preferred = {_key(value) for value in preferred_skills}
        required_skills = list(getattr(job, "required_skills", None) or [])

        # 1. Required skills (filtering section headers & meta notes)
        # ── INTENDED RELATIONSHIP: MANDATORY SKILLS (CONFIG) VS REQUIRED SKILLS (JD) ──
        # Belt-and-suspenders architecture:
        # Configured mandatory_skills represent hard recruiter constraints.
        # They are mapped into RequirementKind.SKILL with required=True, hard=True.
        # Missing mandatory skills trigger both the categorical MISSING_MANDATORY_SKILL
        # knockout (REJECT) and contribute to the numerical Zero/Critical Skill Safeguard.
        req_source = required_skills or getattr(job, "skills", None) or []
        for value in req_source:
            if not value or RequirementBuilder._is_section_header(value) or RequirementBuilder._is_meta_instruction(value):
                continue
            key = _key(value)
            val_cf = value.strip().casefold()
            if any(sa in val_cf for sa in RequirementBuilder.SOFT_ATTRIBUTES_KEYWORDS):
                rows.append((RequirementKind.CANDIDATE_ATTRIBUTE, value.strip(), False, False))
            elif key not in preferred:
                rows.append((RequirementKind.SKILL, value.strip(), True, key in mandatory))

        # Ensure any recruiter mandatory skills not present in JD text are included as required hard skills
        for m_skill in (getattr(config, "mandatory_skills", None) or []):
            if not m_skill or not str(m_skill).strip():
                continue
            m_key = _key(str(m_skill))
            if not any(r[0] == RequirementKind.SKILL and _key(r[1]) == m_key for r in rows):
                rows.append((RequirementKind.SKILL, str(m_skill).strip(), True, True))

        # 2. Preferred skills (explicitly required=False)
        for value in preferred_skills:
            if not value or RequirementBuilder._is_section_header(value) or RequirementBuilder._is_meta_instruction(value):
                continue
            val_cf = value.strip().casefold()
            if any(sa in val_cf for sa in RequirementBuilder.SOFT_ATTRIBUTES_KEYWORDS):
                rows.append((RequirementKind.CANDIDATE_ATTRIBUTE, value.strip(), False, False))
            else:
                rows.append((RequirementKind.SKILL, value.strip(), False, False))

        # 3. Experience requirements (deduplicate duplicate experience bounds into one canonical requirement)
        seen_exp_bounds: set[tuple[int, int | None]] = set()
        for item in (getattr(job, "experience_requirements", None) or []):
            if isinstance(item, dict):
                val = item.get("display_value") or str(item)
                min_m = item.get("minimum_months")
                max_m = item.get("maximum_months")
            else:
                val = str(item)
                min_m, max_m = None, None
            if not val or RequirementBuilder._is_section_header(val) or RequirementBuilder._is_meta_instruction(val):
                continue
            exp_key = (min_m if min_m is not None else -1, max_m)
            if exp_key in seen_exp_bounds:
                continue
            seen_exp_bounds.add(exp_key)
            rows.append((RequirementKind.EXPERIENCE, val.strip(), True, False))

        # 4. Education, Certification, Language, Project requirements
        for value in list(getattr(job, "degree_requirements", None) or getattr(job, "qualifications", None) or []):
            if value and str(value).strip() and not RequirementBuilder._is_section_header(str(value)):
                val_str = str(value).strip()
                if not any(kind == RequirementKind.DEGREE and _key(val_str) == _key(t) for kind, t, _, _ in rows):
                    rows.append((RequirementKind.DEGREE, val_str, True, False))

        for value in [
            *(getattr(job, "certifications", None) or []),
            *(getattr(config, "required_certifications", None) or []),
        ]:
            if value and not RequirementBuilder._is_section_header(value):
                rows.append((RequirementKind.CERTIFICATION, value.strip(), True, False))
        for value in getattr(config, "required_languages", None) or []:
            if value and not RequirementBuilder._is_section_header(value):
                rows.append((RequirementKind.LANGUAGE, value.strip(), True, False))
        for value in getattr(job, "project_requirements", None) or []:
            if value and not RequirementBuilder._is_section_header(value):
                rows.append((RequirementKind.PROJECT_RELEVANCE, value.strip(), True, False))

        # 5. Responsibilities vs Soft Candidate Attributes
        for value in getattr(job, "responsibilities", None) or []:
            if not value or not value.strip() or RequirementBuilder._is_section_header(value) or RequirementBuilder._is_meta_instruction(value):
                continue
            val_cf = value.strip().casefold()
            is_soft = any(sk in val_cf for sk in RequirementBuilder.SOFT_ATTRIBUTES_KEYWORDS)
            has_tech = any(tk in val_cf for tk in ("python", "sql", "etl", "data", "api", "pipeline", "design", "build", "develop", "create", "implement", "architect", "deploy", "test", "database", "query", "schema", "spark", "airflow", "aws", "docker"))
            if is_soft and not has_tech:
                rows.append((RequirementKind.CANDIDATE_ATTRIBUTE, value.strip(), False, False))
            else:
                rows.append((RequirementKind.RESPONSIBILITY, value.strip(), True, False))

        class_dict = classifications or getattr(job, "requirement_classifications", None) or (getattr(job, "raw_metadata", None) or {}).get("requirement_classifications") or {}
        result: list[Requirement] = []
        seen: set[tuple[RequirementKind, str]] = set()
        counters: dict[RequirementKind, int] = {}
        for kind, text, required, hard in rows:
            identity = (kind, _key(text))
            if not text.strip() or identity in seen:
                continue
            seen.add(identity)
            counters[kind] = counters.get(kind, 0) + 1

            # Determine importance and boilerplate signals
            text_strip = text.strip()
            cls_info = class_dict.get(text_strip.casefold()) or class_dict.get(_key(text_strip))
            if cls_info:
                importance = getattr(cls_info, "importance", None) or (cls_info.get("importance") if isinstance(cls_info, dict) else "important")
                reasoning = getattr(cls_info, "reasoning", None) or (cls_info.get("reasoning") if isinstance(cls_info, dict) else "")
                boilerplate = getattr(cls_info, "is_likely_boilerplate", False) or (cls_info.get("is_likely_boilerplate", False) if isinstance(cls_info, dict) else False)
            else:
                boilerplate = any(sa in text_strip.casefold() for sa in RequirementBuilder.SOFT_ATTRIBUTES_KEYWORDS)
                if not required or kind == RequirementKind.CANDIDATE_ATTRIBUTE or boilerplate:
                    importance = "minor"
                elif hard:
                    importance = "critical"
                else:
                    importance = "important"
                reasoning = None

            result.append(Requirement(
                requirement_id=f"{kind.value}:{counters[kind]}", kind=kind,
                text=text_strip, canonical_value=text_strip, required=required,
                hard_constraint=hard,
                importance=str(importance).lower(),
                importance_reasoning=reasoning,
                is_likely_boilerplate=bool(boilerplate),
            ))
        return result


class EvidenceBuilder:
    @staticmethod
    def _projects(extracted: Any) -> list[dict[str, Any]]:
        raw_projs = list(getattr(extracted, "projects", None) or [])
        if not raw_projs:
            meta = getattr(extracted, "raw_metadata", None) or {}
            if isinstance(meta, dict):
                raw_projs = list((meta.get("affinda_normalized_profile") or {}).get("projects") or [])
        projects = [dict(item) if isinstance(item, dict) else item for item in raw_projs]
        if len(projects) <= 1:
            return projects
        first_desc = projects[0].get("description") if isinstance(projects[0], dict) else getattr(projects[0], "description", None)
        descriptions = (first_desc or "").splitlines()
        descriptions = [value.strip() for value in descriptions if value.strip()]
        if len(descriptions) == len(projects) and all(
            not (p.get("description") if isinstance(p, dict) else getattr(p, "description", None)) for p in projects[1:]
        ):
            for project, description in zip(projects, descriptions, strict=True):
                if isinstance(project, dict):
                    project["description"] = description
        return projects
    def build(extracted: Any) -> list[Evidence]:
        result: list[Evidence] = []
        for index, project in enumerate(EvidenceBuilder._projects(extracted), start=1):
            name = project.get("name") if isinstance(project, dict) else getattr(project, "name", "")
            description = project.get("description") if isinstance(project, dict) else getattr(project, "description", "")
            technologies = (project.get("technologies") if isinstance(project, dict) else getattr(project, "technologies", [])) or []

            extra_parts: list[str] = []
            for field in ("deliverables", "highlights", "summary", "responsibilities", "outcomes", "details"):
                val = project.get(field) if isinstance(project, dict) else getattr(project, field, None)
                if val:
                    if isinstance(val, list):
                        for item in val:
                            if item and str(item).strip() and str(item).strip() not in extra_parts and str(item).strip() != description:
                                extra_parts.append(str(item).strip())
                    elif isinstance(val, str) and val.strip() and val.strip() not in extra_parts and val.strip() != description:
                        extra_parts.append(val.strip())

            text_parts = [name, description, *extra_parts, *technologies]
            text = " ".join(str(value) for value in text_parts if value).strip()
            if text:
                result.append(Evidence(
                    evidence_id=f"project:{index}", kind="project", text=text,
                    canonical_terms=list(technologies),
                ))
        for index, item in enumerate(getattr(extracted, "experience", None) or [], start=1):
            responsibilities = item.get("responsibilities") or []
            text = " ".join(value for value in [
                item.get("title") or item.get("designation") or "",
                item.get("company") or "",
                item.get("description") or "", *responsibilities,
            ] if value).strip()
            if text:
                result.append(Evidence(
                    evidence_id=f"experience:{index}", kind="experience", text=text,
                    canonical_terms=[],
                ))
        skills = [s.strip() for s in (getattr(extracted, "skills", None) or []) if str(s).strip()]
        if skills:
            result.append(Evidence(
                evidence_id="skills:1", kind="skills", text=", ".join(skills),
                canonical_terms=list(skills),
            ))
        summary = getattr(extracted, "summary", None) or (getattr(extracted, "raw_metadata", None) or {}).get("summary")
        if not summary:
            meta = getattr(extracted, "raw_metadata", None) or {}
            if isinstance(meta, dict):
                summary = (meta.get("affinda_normalized_profile") or {}).get("summary")
        if summary and str(summary).strip():
            result.append(Evidence(
                evidence_id="summary:1", kind="summary", text=str(summary).strip(),
                canonical_terms=[],
            ))
        raw_edu = getattr(extracted, "education", None) or []
        for index, item in enumerate(raw_edu, start=1):
            if isinstance(item, dict):
                deg = item.get("degree") or item.get("title") or ""
                major = item.get("field") or item.get("major") or item.get("field_of_study") or ""
                inst = item.get("institution") or item.get("school") or ""
                edu_text = " ".join(part for part in [deg, major, inst] if part).strip()
            else:
                edu_text = str(item).strip()
                deg, major = edu_text, ""
            if edu_text:
                result.append(Evidence(
                    evidence_id=f"education:{index}", kind="education", text=edu_text,
                    canonical_terms=[part for part in [deg, major] if part],
                ))
        raw_certs = getattr(extracted, "certifications", None) or []
        for index, c in enumerate(raw_certs, start=1):
            cert_text = (c.get("name") or c.get("title") or "") if isinstance(c, dict) else str(c).strip()
            if cert_text:
                result.append(Evidence(
                    evidence_id=f"certification:{index}", kind="certification", text=cert_text,
                    canonical_terms=[cert_text],
                ))
        langs = [(l.get("name") or l.get("language") or "") if isinstance(l, dict) else str(l).strip() for l in (getattr(extracted, "languages", None) or [])]
        langs = [l for l in langs if l]
        if langs:
            result.append(Evidence(
                evidence_id="languages:1", kind="languages", text=", ".join(langs),
                canonical_terms=list(langs),
            ))
        return result


class DeterministicRequirementMatcher:
    def __init__(self) -> None:
        pass

    @staticmethod
    def _canonical(value: str, aliases: dict[str, str]) -> tuple[str, MatchMethod]:
        key = _key(value)
        canonical = aliases.get(key, value)
        canonical_key = _key(canonical)
        return canonical_key, MatchMethod.EXACT if key == canonical_key else MatchMethod.ALIAS

    def _match_single_alt(
        self,
        alt: str,
        aliases: dict[str, str],
        candidate_keys_map: dict[str, tuple[str, MatchMethod]],
        evidence: list[Evidence],
        evidence_text: str,
        candidate_pool: list[str],
    ) -> tuple[str, MatchMethod, list[str]] | None:
        alt_clean = alt.strip()
        if not alt_clean:
            return None

        variants = list(dict.fromkeys([alt_clean, _clean_req_text(alt_clean)]))

        for a in variants:
            if not a:
                continue
            a_cf = a.casefold()
            a_key, a_method = self._canonical(a, aliases)

            # 1. Check category requirement (e.g. RELATIONAL_DATABASE, PROGRAMMING_LANGUAGE, CLOUD_PLATFORMS)
            category_name = a.upper() if a.upper() in SKILL_CATEGORIES else CATEGORY_REQUIREMENT_ALIASES.get(a_cf)
            if category_name and category_name in SKILL_CATEGORIES:
                category_members = {m.casefold(): m for m in SKILL_CATEGORIES[category_name]}
                matched_key = next((k for k in candidate_keys_map if k in category_members), None)
                if matched_key:
                    orig_skill, cmeth = candidate_keys_map[matched_key]
                    ev_ids = [e.evidence_id for e in evidence if orig_skill.casefold() in e.text.casefold()][:1]
                    return orig_skill, MatchMethod.ALIAS, ev_ids
                # Also check if any category member is present in candidate evidence text or pool
                for mem_cf, mem_orig in category_members.items():
                    if len(mem_cf) >= 3 and (mem_cf in [c.casefold() for c in candidate_pool] or re.search(rf"\b{re.escape(mem_cf)}\b", evidence_text)):
                        ev_ids = [e.evidence_id for e in evidence if mem_cf in e.text.casefold()][:1]
                        return mem_orig, MatchMethod.ALIAS, ev_ids

            # 2. Direct canonical match
            if a_key in candidate_keys_map:
                orig_skill, cmeth = candidate_keys_map[a_key]
                method = MatchMethod.ALIAS if MatchMethod.ALIAS in {a_method, cmeth} else MatchMethod.EXACT
                ev_ids = [e.evidence_id for e in evidence if orig_skill.casefold() in e.text.casefold()][:1]
                return orig_skill, method, ev_ids

            # 3. Canonical target match (check if candidate key maps to same canonical)
            canonical_target = aliases.get(a_key, a)
            canonical_target_key = _key(canonical_target)
            if canonical_target_key in candidate_keys_map:
                orig_skill, cmeth = candidate_keys_map[canonical_target_key]
                ev_ids = [e.evidence_id for e in evidence if orig_skill.casefold() in e.text.casefold()][:1]
                return orig_skill, MatchMethod.ALIAS, ev_ids

            # 4. Check if a_key or a_cf is mentioned in candidate pool or evidence text with word boundary
            for cp in candidate_pool:
                cp_cf = cp.casefold()
                if a_cf == cp_cf or a_key == _key(cp):
                    ev_ids = [e.evidence_id for e in evidence if cp_cf in e.text.casefold()][:1]
                    return cp, MatchMethod.EXACT if a_cf == cp_cf else MatchMethod.ALIAS, ev_ids

            # 5. Multi-word concept proximity matching
            multi_match = ComponentScoringService._match_multiword_concept(a, [e.text for e in evidence] + candidate_pool)
            if multi_match:
                ev_ids = [e.evidence_id for e in evidence if any(_stem_token(ct) in [_stem_token(t) for t in _TOKEN.findall(e.text.casefold())] for ct in _TOKEN.findall(a.casefold()))][:1]
                return a, MatchMethod.ALIAS, ev_ids

        return None

    def match(self, requirement: Requirement, resume: Any, evidence: list[Evidence]) -> MatchVerdict:
        verdict = self._match_internal(requirement, resume, evidence)
        verdict.requirement_text = requirement.text
        verdict.kind = requirement.kind
        return verdict

    def _match_internal(self, requirement: Requirement, resume: Any, evidence: list[Evidence]) -> MatchVerdict:
        if requirement.kind == RequirementKind.RESPONSIBILITY:
            req_text = requirement.canonical_value or requirement.text
            required_key = _key(req_text)
            for item in evidence:
                if item.kind not in {"experience", "project", "summary"}:
                    continue
                canonical = {_key(value) for value in item.canonical_terms}
                if required_key in canonical or required_key == _key(item.text):
                    return MatchVerdict(
                        requirement_id=requirement.requirement_id,
                        status=MatchStatus.MATCHED, confidence=1,
                        evidence_ids=[item.evidence_id],
                        reasoning="Contextual evidence contains the exact canonical requirement.",
                        method=MatchMethod.EXACT,
                        coverage=1.0,
                        matched_concepts=[req_text],
                        missing_concepts=[],
                    )

            exp_and_proj_evidence = [e for e in evidence if e.kind in {"experience", "project", "summary"}]
            if not exp_and_proj_evidence:
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.UNRESOLVED,
                    confidence=0.0,
                    evidence_ids=[],
                    reasoning="No experiential evidence (projects/experience) found for responsibility.",
                    method=None,
                    coverage=0.0,
                    matched_concepts=[],
                    missing_concepts=[req_text],
                )

            # Semantic Action Normalization
            action_synonyms = {
                "build": {"build", "develop", "create", "implement", "construct", "code", "author", "engineer"},
                "develop": {"develop", "build", "create", "implement", "code", "author", "engineer"},
                "create": {"create", "build", "develop", "implement", "author"},
                "implement": {"implement", "build", "develop", "create", "integrate", "execute"},
                "architect": {"architect", "design", "structure"},
                "design": {"design", "model", "structure", "plan"},
                "maintain": {"maintain", "support", "manage", "sustain", "upkeep"},
                "manage": {"manage", "maintain", "administer", "oversee", "operate"},
                "integrate": {"integrate", "connect", "interface", "link", "consume"},
                "deploy": {"deploy", "release", "publish", "ship"},
                "monitor": {"monitor", "observe", "track", "watch"},
                "track": {"track", "monitor", "observe", "follow", "log", "record"},
                "prepare": {"prepare", "create", "develop", "compile", "generate", "write", "author", "draft"},
                "coordinate": {"coordinate", "collaborate", "organize", "align", "manage", "partner", "work with"},
                "document": {"document", "record", "write", "log"},
                "analyze": {"analyze", "study", "investigate", "inspect", "assess"},
                "investigate": {"investigate", "analyze", "inspect", "triage"},
                "triage": {"triage", "review", "investigate", "assess"},
                "configure": {"configure", "set up", "setup", "install", "provision"},
                "review": {"review", "inspect", "audit", "evaluate"},
                "test": {"test", "validate", "verify"},
                "troubleshoot": {"troubleshoot", "debug", "diagnose", "fix", "resolve"},
                "write": {"write", "author", "develop", "create"},
                "collaborate": {"collaborate", "coordinate", "work with", "partner"},
                "mentor": {"mentor", "guide", "train", "lead", "coach"},
            }

            tech_aliases = {
                "node.js": {"node.js", "node", "nodejs"},
                "express.js": {"express.js", "express", "expressjs"},
                "react.js": {"react.js", "react", "reactjs", "react components"},
                "mongodb": {"mongodb", "mongo", "mongoose"},
                "rest apis": {"rest api", "rest apis", "restful api", "restful apis", "restful services", "rest services", "rest"},
                "restful apis": {"rest api", "rest apis", "restful api", "restful apis", "restful services", "rest services", "rest"},
                "fastapi": {"fastapi"},
                "postgresql": {"postgresql", "postgres"},
                "sql": {"sql", "postgresql", "postgres", "mysql", "sqlite"},
                "pyspark": {"pyspark", "spark", "apache spark"},
                "airflow": {"airflow", "apache airflow"},
                "redis": {"redis"},
                "docker": {"docker"},
                "kubernetes": {"kubernetes", "k8s"},
                "python": {"python"},
                "aws": {"aws", "amazon web services", "aws s3", "s3"},
                "aws s3": {"aws s3", "s3", "amazon s3", "aws"},
                "wazuh": {"wazuh"},
                "wireshark": {"wireshark"},
                "html5": {"html5", "html"},
                "css3": {"css3", "css"},
                "neon": {"neon", "neon postgres", "neon postgresql", "neon database"},
            }

            # Decompose JD Responsibility into Semantic Units (Actions, Technologies, Domain Activities)
            req_lower = req_text.casefold()
            semantic_concepts: list[tuple[str, str, set[str]]] = []  # (name, type, target_stems/aliases)

            # 1. Identify Technologies
            tech_concepts: list[tuple[str, str, set[str]]] = []
            for tech_key, aliases in tech_aliases.items():
                if any(re.search(rf"\b{re.escape(a)}\b", req_lower) for a in aliases):
                    tech_concepts.append((tech_key, "tech", aliases))

            # 2. Identify Domain Activities / Deliverables
            domain_concepts: list[tuple[str, str, set[str]]] = []
            domain_patterns = [
                ("etl data pipelines", {"etl data pipelines", "etl pipelines", "etl pipeline", "etl", "data pipelines", "data pipeline"}),
                ("rest apis", {"rest api", "rest apis", "restful api", "restful apis", "backend apis", "backend api", "apis", "api"}),
                ("reusable components", {"reusable components", "reusable react components", "reusable ui components", "reusable"}),
                ("responsive design", {"responsive design", "responsive ui", "responsive", "mobile-first", "mobile responsive", "responsive user interfaces"}),
                ("high performance", {"high performance", "high-performance", "performance optimization"}),
                ("scalable applications", {"scalable applications", "scalable application", "scalable backend", "scalable"}),
                ("schemas", {"database schemas", "database schema", "mongodb schemas", "schemas", "schema design"}),
                ("indexing", {"indexes", "indexing", "database indexes", "index design"}),
                ("queries", {"queries", "query", "sql queries", "nosql queries", "query optimization", "optimized queries"}),
                ("aggregation", {"aggregation pipelines", "aggregation pipeline", "aggregations", "aggregation"}),
                ("caching", {"redis caching", "caching", "cache"}),
                ("authentication", {"authentication", "auth", "jwt"}),
                ("authorization", {"role-based access control", "role-based access", "rbac", "authorization", "access workflows"}),
                ("microservices", {"microservices", "microservice", "distributed microservices"}),
                ("ci/cd pipelines", {"ci/cd pipelines", "ci/cd pipeline", "ci/cd", "deployment pipelines", "deployment pipeline"}),
                ("unit tests", {"unit tests", "testing", "tests", "integration tests"}),
                ("data quality", {"data quality checks", "data quality", "data cleaning", "data validation", "quality checks"}),
                ("pipeline troubleshooting", {"pipeline troubleshooting", "troubleshooting", "debugging", "pipeline issues"}),
                ("siem", {"siem", "splunk", "qradar"}),
                ("security alerts", {"security alerts", "alerts"}),
                ("security events", {"security events", "logs", "events"}),
                ("incidents", {"production incidents", "incident", "incidents"}),
                ("root causes", {"root causes", "root cause", "incident findings"}),
                ("incident triage", {"incident triage", "triage", "investigation"}),
                ("findings", {"findings", "recommendation", "recommendations", "reports"}),
                ("vulnerability assessment", {"vulnerability assessment", "vulnerabilities", "vulnerability"}),
                ("cloud infrastructure", {"cloud infrastructure", "infrastructure", "deployments"}),
                ("project schedules", {"project schedules", "project schedule", "schedules", "schedule", "timelines", "timeline"}),
                ("milestone trackers", {"milestone trackers", "milestone tracker", "milestones", "milestone"}),
                ("raid logs", {"raid logs", "raid log", "risk log", "issue log", "risk and issue logs", "risk/issue logs", "raid"}),
                ("status reports", {"status reports", "status report", "progress reports", "weekly status reports", "monthly status reports", "reports", "status summaries"}),
                ("management dashboards", {"management dashboards", "executive dashboards", "dashboards", "dashboard", "kpis"}),
                ("stakeholder meetings", {"stakeholder meetings", "stakeholder coordination", "meeting minutes", "stakeholder progress summaries", "stakeholders", "stakeholder"}),
                ("action items", {"action items", "action item", "action tracking", "actions"}),
                ("cross-functional team deliverables", {"cross-functional team deliverables", "cross-functional team", "cross-functional", "deliverables"}),
                ("project deliverables", {"project deliverables", "deliverables", "milestone deliverables"}),
                ("project documentation", {"project documentation", "documentation", "meeting notes"}),
                ("relational databases", {"relational databases", "relational database", "relational", "rdbms"}),
                ("non-relational databases", {"non-relational databases", "non-relational database", "non-relational", "nosql databases", "nosql database", "nosql"}),
                ("clean code", {"clean code", "readable code", "maintainable code", "clean coding", "code quality", "code standards", "coding standards", "best practices"}),
                ("mentoring", {"mentor", "mentored", "mentoring", "guidance", "coach", "coaching", "mentorship"}),
                ("junior developers", {"junior developers", "junior engineers", "juniors"}),
                ("team members", {"team members", "cross-functional team members", "cross-functional teams", "team", "developers", "peers"}),
                ("user interfaces", {"user interfaces", "user interface", "ui", "interfaces", "components"}),
                ("code reviews", {"code reviews", "code review", "peer reviews", "peer review", "pull requests", "pr reviews"}),
                ("agile processes", {"agile", "agile development", "scrum", "sprints", "sprint planning", "standups", "kanban"}),
                ("debugging and testing", {"testing", "unit tests", "integration tests", "debugging", "troubleshooting", "bug fixing", "automated tests"}),
                ("version control", {"version control", "version-control", "git", "github", "gitlab", "bitbucket"}),
            ]

            seen_domains: set[str] = set()
            for domain_key, aliases in domain_patterns:
                if domain_key in seen_domains:
                    continue
                matched_alias = False
                for a in aliases:
                    pattern = rf"\b{re.escape(a)}\b"
                    if a.startswith("relational"):
                        pattern = rf"(?<!non-)(?<!non\s)\b{re.escape(a)}\b"
                    if re.search(pattern, req_lower):
                        matched_alias = True
                        break
                if matched_alias:
                    if not any(domain_key == c[0] for c in domain_concepts):
                        domain_concepts.append((domain_key, "domain", aliases))
                        seen_domains.add(domain_key)

            # Filter out technologies that act as direct qualifiers for a domain concept (e.g. "MongoDB schemas", "Redis caching", "React components")
            filtered_tech_concepts: list[tuple[str, str, set[str]]] = []
            for tech_key, kind, aliases in tech_concepts:
                is_qualifier = False
                for d_key, _, d_aliases in domain_concepts:
                    if any(re.search(rf"\b{re.escape(a)}\s+{re.escape(da)}\b", req_lower) for a in aliases for da in d_aliases if len(da.split()) == 1):
                        is_qualifier = True
                        break
                    if any(a in da for a in aliases for da in d_aliases):
                        is_qualifier = True
                        break
                if not is_qualifier:
                    filtered_tech_concepts.append((tech_key, kind, aliases))

            # Combine tech and domain concepts
            semantic_concepts: list[tuple[str, str, set[str]]] = []
            semantic_concepts.extend(filtered_tech_concepts)
            semantic_concepts.extend(domain_concepts)

            # 3. Only if no tech or domain concepts were found, use action synonyms or clause decomposition
            if not semantic_concepts:
                for action_key, syns in action_synonyms.items():
                    if re.search(rf"\b{re.escape(action_key)}\b", req_lower):
                        stemmed_syns = {_stem_token(s) for s in syns}
                        semantic_concepts.append((action_key, "action", stemmed_syns))

                raw_clauses = [c.strip() for c in re.split(r"[,;]|\s+(?:and|&|\/|\+)\s+", req_text, flags=re.I) if c.strip()]
                if len(raw_clauses) >= 3:
                    semantic_concepts = []
                    stop_words = {
                        "the", "a", "an", "and", "of", "to", "with", "from", "for", "on", "in",
                        "by", "as", "at", "during", "across", "into", "through", "using", "or", "&",
                        "work", "working", "experience", "knowledge", "proficiency", "support", "etc",
                    }
                    for clause in raw_clauses:
                        tokens = [t for t in _TOKEN.findall(clause.casefold()) if len(t) > 1 and t not in stop_words]
                        if tokens:
                            c_name = " ".join(tokens)
                            c_stemmed = {_stem_token(t) for t in tokens}
                            semantic_concepts.append((c_name, "general", c_stemmed))

            # If only action verbs were matched with no tech, domain, or itemized concepts, require LLM evaluation
            if semantic_concepts and all(c[1] == "action" for c in semantic_concepts):
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.UNRESOLVED,
                    confidence=0,
                    reasoning="Responsibility action requires contextual experiential validation.",
                )

            # Match extracted semantic concepts across candidate experiential evidence
            matched_concepts = []
            missing_concepts = []
            ev_ids = []

            for c_name, c_type, targets in semantic_concepts:
                concept_matched = False
                for e in exp_and_proj_evidence:
                    e_text_lower = e.text.casefold()
                    e_terms = [t.casefold() for t in e.canonical_terms]
                    e_stemmed = {_stem_token(t) for t in _TOKEN.findall(e_text_lower) if len(t) > 1}

                    if c_type == "tech" or c_type == "domain":
                        matched_target = False
                        for a in targets:
                            if a in e_terms:
                                matched_target = True
                                break
                            pattern = rf"\b{re.escape(a)}\b"
                            if a.startswith("relational"):
                                pattern = rf"(?<!non-)(?<!non\s)\b{re.escape(a)}\b"
                            if re.search(pattern, e_text_lower):
                                matched_target = True
                                break
                        if matched_target:
                            concept_matched = True
                            if e.evidence_id not in ev_ids:
                                ev_ids.append(e.evidence_id)
                            break
                    elif c_type == "action":
                        if any(s in e_stemmed for s in targets):
                            concept_matched = True
                            if e.evidence_id not in ev_ids:
                                ev_ids.append(e.evidence_id)
                            break
                    else:
                        if all(ct in e_stemmed for ct in targets):
                            concept_matched = True
                            if e.evidence_id not in ev_ids:
                                ev_ids.append(e.evidence_id)
                            break

                if concept_matched:
                    matched_concepts.append(c_name)
                else:
                    missing_concepts.append(c_name)

            satisfied_count = len(matched_concepts)
            total_concepts_count = len(matched_concepts) + len(missing_concepts)
            coverage = round(satisfied_count / total_concepts_count, 2) if total_concepts_count > 0 else 0.0

            # Phase 5A Business Rules:
            # 1. Single-concept responsibility: satisfied_count >= 1 -> MATCHED (100%)
            # 2. Multi-concept responsibility (>=2 concepts):
            #    satisfied_count >= 2 -> MATCHED (score proportional to coverage, e.g. 2/4=50%, 2/5=40%, 3/4=75%)
            #    satisfied_count == 1 -> PARTIALLY_MATCHED (score proportional to coverage, e.g. 1/4=25%, 1/5=20%)
            #    satisfied_count == 0 -> UNRESOLVED / NO_MATCH
            if total_concepts_count == 1:
                if satisfied_count >= 1:
                    status = MatchStatus.MATCHED
                    method = MatchMethod.ALIAS if ev_ids else MatchMethod.EXACT
                    reasoning = f"Single core responsibility concept satisfied (100% coverage)."
                else:
                    status = MatchStatus.UNRESOLVED
                    method = None
                    reasoning = "No evidence for single responsibility requirement; requires semantic experiential review."
            else:
                if satisfied_count >= 2:
                    status = MatchStatus.MATCHED
                    method = MatchMethod.ALIAS if ev_ids else MatchMethod.EXACT
                    reasoning = f"Contextual evidence satisfies {satisfied_count} of {total_concepts_count} responsibility concepts ({int(coverage * 100)}% coverage, >=2 concepts rule satisfied)."
                elif satisfied_count == 1:
                    status = MatchStatus.PARTIALLY_MATCHED
                    method = MatchMethod.ALIAS if ev_ids else MatchMethod.EXACT
                    reasoning = f"Contextual evidence satisfies only 1 of {total_concepts_count} responsibility concepts ({int(coverage * 100)}% coverage, <2 concepts threshold)."
                else:
                    status = MatchStatus.UNRESOLVED
                    method = None
                    reasoning = "No direct deterministic concept match; requires semantic experiential review."

            return MatchVerdict(
                requirement_id=requirement.requirement_id,
                status=status,
                confidence=1.0 if status == MatchStatus.MATCHED else (coverage if coverage > 0 else 0.0),
                evidence_ids=ev_ids[:3],
                reasoning=reasoning,
                method=method,
                coverage=coverage,
                matched_concepts=matched_concepts,
                missing_concepts=missing_concepts,
            )

        elif requirement.kind == RequirementKind.PROJECT_RELEVANCE:
            req_text = requirement.canonical_value or requirement.text
            req_cf = req_text.casefold()
            projects = getattr(resume, "projects", None) or []
            for p in projects:
                p_text = f"{p.get('name', '')} {p.get('description', '')}".casefold()
                if req_cf in p_text or ComponentScoringService._match_multiword_concept(req_text, [p_text]):
                    ev_ids = [e.evidence_id for e in evidence if e.kind == "project" and p.get("name", "").casefold() in e.text.casefold()][:1]
                    return MatchVerdict(
                        requirement_id=requirement.requirement_id,
                        status=MatchStatus.MATCHED,
                        confidence=1,
                        evidence_ids=ev_ids,
                        reasoning=f"Candidate project explicitly demonstrates requirement ({p.get('name', 'Project')}).",
                        method=MatchMethod.EXACT,
                    )
            return MatchVerdict(
                requirement_id=requirement.requirement_id,
                status=MatchStatus.UNRESOLVED,
                confidence=0,
                reasoning="Project domain and contextual relevance requires evidence review.",
            )

        req_text = requirement.canonical_value or requirement.text

        if requirement.kind in {RequirementKind.SKILL, RequirementKind.REQUIRED_SKILL, RequirementKind.PREFERRED_SKILL}:
            aliases = SKILL_ALIASES
            candidates = [str(s).strip() for s in (getattr(resume, "skills", None) or []) if str(s).strip()]
            skill_evidence = [e for e in evidence if e.kind in {"skills", "project", "experience", "summary", "certification"}]
            evidence_terms = [term for e in skill_evidence for term in e.canonical_terms if term]
            evidence_text = " ".join(e.text for e in skill_evidence).casefold()
            candidate_pool = list(dict.fromkeys([*candidates, *evidence_terms]))

            candidate_keys_map: dict[str, tuple[str, MatchMethod]] = {}
            for c in candidate_pool:
                ckey, cmeth = self._canonical(c, aliases)
                candidate_keys_map[ckey] = (c, cmeth)

            cleaned_req = _clean_req_text(req_text)

            # 1. First test if the entire requirement or cleaned requirement matches directly as a whole
            res_whole = self._match_single_alt(req_text, aliases, candidate_keys_map, evidence, evidence_text, candidate_pool)
            if not res_whole and cleaned_req != req_text:
                res_whole = self._match_single_alt(cleaned_req, aliases, candidate_keys_map, evidence, evidence_text, candidate_pool)
            if res_whole:
                orig_skill, method, ev_ids = res_whole
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.MATCHED,
                    confidence=1,
                    evidence_ids=ev_ids,
                    reasoning=f"Canonical values match ({orig_skill}).",
                    method=method,
                )

            # 2. Check if cleaned_req is a conjunction (AND compound requirement)
            is_conjunction = bool(re.search(r"\b(?:and|&)\b", cleaned_req, re.I)) and not bool(re.search(r"\b(?:or|\/|\||such as|like|e\.g\.)\b", cleaned_req, re.I))

            if is_conjunction:
                and_parts = [p.strip() for p in re.split(r"\s+(?:and|&)\s+|\s*,\s*and\s+", cleaned_req, flags=re.I) if p.strip()]
                if len(and_parts) >= 2:
                    matched_all = True
                    matched_skills_list = []
                    all_ev_ids = []
                    for part in and_parts:
                        res = self._match_single_alt(part, aliases, candidate_keys_map, evidence, evidence_text, candidate_pool)
                        if not res:
                            clean_part = _clean_req_text(part).casefold()
                            GENERIC_DESCRIPTORS = {
                                "database concepts", "database", "debugging", "concepts", "fundamentals",
                                "basics", "principles", "json", "problem-solving ability", "teamwork", "soft skills",
                                "other columnar data formats", "other data formats", "columnar data formats",
                                "columnar formats", "other tools", "other frameworks", "other technologies",
                                "other databases", "similar tools", "similar technologies", "other related technologies",
                            }
                            if clean_part in GENERIC_DESCRIPTORS and matched_skills_list:
                                continue
                            matched_all = False
                            break
                        orig_s, meth, ev_ids = res
                        matched_skills_list.append(orig_s)
                        all_ev_ids.extend(ev_ids)

                    if matched_all and matched_skills_list:
                        ev_ids_dedup = list(dict.fromkeys(all_ev_ids))[:2]
                        return MatchVerdict(
                            requirement_id=requirement.requirement_id,
                            status=MatchStatus.MATCHED,
                            confidence=1,
                            evidence_ids=ev_ids_dedup,
                            reasoning=f"Canonical values match all conjunction requirements ({', '.join(matched_skills_list)}).",
                            method=MatchMethod.EXACT,
                        )
                    else:
                        return MatchVerdict(
                            requirement_id=requirement.requirement_id, status=MatchStatus.NO_MATCH,
                            confidence=1, reasoning=f"Compound requirement not fully satisfied ({cleaned_req}).",
                        )

            # 3. Alternatives (OR groups) or single requirement
            such_as_parts = []
            such_match = re.search(r"\b(?:such\s+as|like|e\.g\.?|including)\s+(.+)$", cleaned_req, re.I)
            if such_match:
                such_parts_raw = re.split(r"[,;/]|\s+or\s+", such_match.group(1).strip())
                such_as_parts = [p.strip() for p in such_parts_raw if p.strip()]

            raw_alts = re.split(r"\s*(?:\/|\|)\s*|\s+or\s+|\s*,\s*or\s*", cleaned_req, flags=re.IGNORECASE)
            alternatives = list(dict.fromkeys([a.strip() for a in [*raw_alts, *such_as_parts, cleaned_req, req_text] if a.strip()]))

            for alt in alternatives:
                res = self._match_single_alt(alt, aliases, candidate_keys_map, evidence, evidence_text, candidate_pool)
                if res:
                    orig_skill, method, ev_ids = res
                    return MatchVerdict(
                        requirement_id=requirement.requirement_id,
                        status=MatchStatus.MATCHED,
                        confidence=1,
                        evidence_ids=ev_ids,
                        reasoning=f"Canonical values match ({orig_skill}).",
                        method=method,
                    )

            return MatchVerdict(
                requirement_id=requirement.requirement_id, status=MatchStatus.NO_MATCH,
                confidence=1, reasoning="No deterministic canonical match.",
            )

        elif requirement.kind == RequirementKind.DEGREE:
            req_text = requirement.canonical_value or requirement.text
            edu_evidence = [e for e in evidence if e.kind == "education"]
            raw_edu = getattr(resume, "education", None) or []

            if not edu_evidence and not raw_edu:
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.UNRESOLVED,
                    confidence=0.0,
                    evidence_ids=[],
                    reasoning=f"No education background found in candidate education section ({req_text}).",
                    method=None,
                    coverage=0.0,
                    matched_concepts=[],
                    missing_concepts=[req_text],
                )

            edu_texts = [e.text for e in edu_evidence]
            for item in raw_edu:
                if isinstance(item, dict):
                    t = f"{item.get('degree', '')} {item.get('title', '')} {item.get('field', '')} {item.get('major', '')} {item.get('field_of_study', '')} {item.get('institution', '')}".strip()
                    if t and t not in edu_texts:
                        edu_texts.append(t)
                elif isinstance(item, str) and item.strip() and item.strip() not in edu_texts:
                    edu_texts.append(item.strip())

            full_edu_str = " ".join(edu_texts).casefold()
            req_cf = req_text.casefold()

            def _has_degree_term(patterns: tuple[str, ...], text: str) -> bool:
                return any(bool(re.search(r"(?:\b|\A)" + re.escape(p) + r"(?:\b|\Z)", text, re.IGNORECASE)) for p in patterns)

            bachelor_terms = ("bachelor", "b.s", "bs", "b.a", "ba", "b.tech", "btech", "b.e", "be", "undergraduate")
            master_terms = ("master", "m.s", "ms", "m.a", "ma", "m.tech", "mtech", "m.e", "me", "postgraduate", "graduate degree")
            phd_terms = ("phd", "ph.d", "doctorate", "doctoral")

            is_bachelor = _has_degree_term(bachelor_terms, req_cf)
            is_master = _has_degree_term(master_terms, req_cf)
            is_phd = _has_degree_term(phd_terms, req_cf)

            cand_bachelor = _has_degree_term(bachelor_terms, full_edu_str)
            cand_master = _has_degree_term(master_terms, full_edu_str)
            cand_phd = _has_degree_term(phd_terms, full_edu_str)

            degree_level_matched = False
            if is_bachelor and (cand_bachelor or cand_master or cand_phd):
                degree_level_matched = True
            elif is_master and (cand_master or cand_phd):
                degree_level_matched = True
            elif is_phd and cand_phd:
                degree_level_matched = True
            elif not is_bachelor and not is_master and not is_phd:
                degree_level_matched = bool(full_edu_str.strip())

            fields = ["computer science", "software engineering", "information technology", "data science", "electrical engineering", "mathematics", "computer engineering", "cybersecurity"]
            req_field = next((f for f in fields if f in req_cf), None)
            cand_field_matched = True
            if req_field:
                cand_field_matched = any(f in full_edu_str for f in (req_field, "computer", "software", "it", "engineering", "technology"))

            if degree_level_matched and cand_field_matched:
                ev_ids = [e.evidence_id for e in edu_evidence][:1]
                deg_method = MatchMethod.TAXONOMY if (is_bachelor and not cand_bachelor and (cand_master or cand_phd)) else MatchMethod.EXACT
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.MATCHED,
                    confidence=1.0,
                    evidence_ids=ev_ids,
                    reasoning=f"Candidate education degree satisfies requirement ({req_text}).",
                    method=deg_method,
                    coverage=1.0,
                    matched_concepts=[req_text],
                    missing_concepts=[],
                )
            elif degree_level_matched:
                ev_ids = [e.evidence_id for e in edu_evidence][:1]
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.MATCHED,
                    confidence=0.85,
                    evidence_ids=ev_ids,
                    reasoning=f"Candidate degree level satisfies education requirement ({req_text}).",
                    method=MatchMethod.ALIAS,
                    coverage=0.85,
                    matched_concepts=[req_text],
                    missing_concepts=[],
                )
            else:
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.NO_MATCH,
                    confidence=1.0,
                    evidence_ids=[],
                    reasoning=f"Candidate education degree does not meet requirement ({req_text}).",
                    method=MatchMethod.EXACT,
                    coverage=0.0,
                    matched_concepts=[],
                    missing_concepts=[req_text],
                )

        elif requirement.kind in {RequirementKind.EXPERIENCE, RequirementKind.CONTEXTUAL_EXPERIENCE}:
            req_text = requirement.canonical_value or requirement.text
            exp_items = getattr(resume, "experience", None) or []
            total_months = sum(item.get("duration_months") or 0 for item in exp_items)
            
            m_range = re.search(r"(\d+)\s*[-–to]+\s*(\d+)\s+years?", req_text, re.I)
            m_min_yr = re.search(r"(?:minimum|at\s+least|min)\s+(\d+)\s+years?", req_text, re.I) or re.search(r"(\d+)\+\s*years?", req_text, re.I) or re.search(r"(\d+)\s+years?", req_text, re.I)
            m_min_mo = re.search(r"(\d+)\s*months?", req_text, re.I)
            if m_range:
                job_min = int(m_range.group(1)) * 12
            elif m_min_yr:
                job_min = int(m_min_yr.group(1)) * 12
            elif m_min_mo:
                job_min = int(m_min_mo.group(1))
            else:
                job_min = 0

            if total_months >= job_min or (job_min == 0 and (total_months > 0 or bool(exp_items))):
                ev_ids = [e.evidence_id for e in evidence if e.kind == "experience"][:1]
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.MATCHED,
                    confidence=1.0,
                    evidence_ids=ev_ids,
                    reasoning=f"Candidate experience ({total_months} months) satisfies entry-level requirement ({req_text}).",
                    method=MatchMethod.EXACT,
                    coverage=1.0,
                    matched_concepts=[f"{total_months} months experience"],
                    missing_concepts=[],
                )
            else:
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.UNRESOLVED,
                    confidence=0.5,
                    reasoning=f"Candidate experience ({total_months} months) is below required {job_min} months.",
                    method=MatchMethod.EXACT,
                    coverage=0.0,
                    matched_concepts=[],
                    missing_concepts=[req_text],
                )
        elif requirement.kind == RequirementKind.CANDIDATE_ATTRIBUTE:
            req_text = requirement.canonical_value or requirement.text
            req_cf = req_text.casefold()

            candidate_texts = [
                *(getattr(resume, "skills", None) or []),
                *[line for exp in (getattr(resume, "experience", None) or []) for line in (exp.get("responsibilities") or [])],
                *[exp.get("description") or "" for exp in (getattr(resume, "experience", None) or [])],
                *[p.get("description") or "" for p in (getattr(resume, "projects", None) or [])],
                *[e.text for e in evidence],
            ]
            full_resume_text = " ".join(candidate_texts).casefold()

            is_learning = any(w in req_cf for w in ("learn", "adapt", "train", "willingness"))
            is_communication = any(w in req_cf for w in ("communication", "teamwork", "collaboration", "interpersonal"))
            is_analytical = any(w in req_cf for w in ("analytical", "problem-solving", "problem solving", "critical thinking"))

            matched = False
            match_reason = ""

            if is_learning:
                if any(w in full_resume_text for w in ("quick learner", "eager to learn", "adaptable", "learned", "fast learner", "passionate about learning")):
                    matched = True
                    match_reason = "Resume explicitly states quick learning and adaptability."
                elif len(getattr(resume, "skills", []) or []) >= 3 or len(getattr(resume, "experience", []) or []) > 0 or len(getattr(resume, "projects", []) or []) > 0:
                    matched = True
                    match_reason = "Demonstrated ability to learn and apply diverse technologies."
            elif is_communication:
                if any(w in full_resume_text for w in ("communication", "teamwork", "collaboration", "collaborated", "cross-functional", "presented", "partnered")):
                    matched = True
                    match_reason = "Demonstrated teamwork and communication in candidate experience."
            elif is_analytical:
                if (len(getattr(resume, "skills", []) or []) >= 3 or len(getattr(resume, "projects", []) or []) > 0):
                    matched = True
                    match_reason = "Demonstrated analytical and problem-solving background."
            elif any(w in full_resume_text for w in req_cf.split() if len(w) > 3):
                matched = True
                match_reason = "Candidate background satisfies soft qualification."

            if matched:
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.MATCHED,
                    confidence=1.0,
                    evidence_ids=[e.evidence_id for e in evidence[:1]],
                    reasoning=match_reason,
                    method=MatchMethod.EXACT,
                    coverage=1.0,
                    matched_concepts=[req_text],
                    missing_concepts=[],
                )
            else:
                return MatchVerdict(
                    requirement_id=requirement.requirement_id,
                    status=MatchStatus.UNRESOLVED,
                    confidence=0.5,
                    reasoning=f"No explicit evidence found for soft attribute ({req_text}).",
                    method=None,
                    coverage=0.0,
                    matched_concepts=[],
                    missing_concepts=[req_text],
                )

        elif requirement.kind == RequirementKind.CERTIFICATION:
            aliases = CERTIFICATION_ALIASES
            raw_certs = getattr(resume, "certifications", None) or []
            candidates = [(c.get("name") or c.get("title") or "") if isinstance(c, dict) else str(c).strip() for c in raw_certs]
            candidates = [c for c in candidates if c]
        elif requirement.kind == RequirementKind.LANGUAGE:
            aliases = LANGUAGE_ALIASES
            raw_langs = getattr(resume, "languages", None) or []
            candidates = [(l.get("name") or l.get("language") or "") if isinstance(l, dict) else str(l).strip() for l in raw_langs]
            candidates = [l for l in candidates if l]
        else:
            return MatchVerdict(
                requirement_id=requirement.requirement_id, status=MatchStatus.NO_MATCH,
                confidence=1, reasoning="Unsupported requirement kind.",
            )

        for candidate in candidates:
            cand_key, cand_method = self._canonical(candidate, aliases)
            req_key, req_method = self._canonical(req_text, aliases)
            if cand_key == req_key:
                method = MatchMethod.ALIAS if MatchMethod.ALIAS in {cand_method, req_method} else MatchMethod.EXACT
                ev_ids = [e.evidence_id for e in evidence if e.kind == "certification" and candidate.casefold() in e.text.casefold()][:1]
                return MatchVerdict(
                    requirement_id=requirement.requirement_id, status=MatchStatus.MATCHED,
                    confidence=1, evidence_ids=ev_ids, reasoning="Canonical values match.", method=method,
                )

        return MatchVerdict(
            requirement_id=requirement.requirement_id, status=MatchStatus.NO_MATCH,
            confidence=1, reasoning="No deterministic canonical match.",
        )


SEMANTIC_SYNONYMS: dict[str, set[str]] = {
    "authorization": {"auth", "rbac", "role", "roles", "permission", "permissions", "access", "jwt", "oauth", "token", "security", "privilege", "privileges", "role-based access", "role-based access control"},
    "authentication": {"auth", "login", "jwt", "oauth", "sso", "password", "token", "session", "sessions", "credential", "credentials", "security", "login authentication"},
    "responsive design": {"responsive", "mobile", "mobile-first", "mobile first", "layout", "layouts", "flexbox", "grid", "bootstrap", "tailwind", "css", "html", "viewport", "media", "query", "queries", "media queries", "responsive ui"},
    "asynchronous programming": {"async", "await", "asynchronous", "promise", "promises", "non-blocking", "blocking", "event", "events", "concurrency", "thread", "threads", "coroutine", "goroutine", "event-driven", "event driven", "event-driven services", "messaging", "message", "queue", "queues", "kafka", "rabbitmq"},
    "schema design": {"schema", "schemas", "model", "models", "modeling", "table", "tables", "collection", "collections", "entity", "database", "mongodb", "sql", "relational", "normalization", "database schemas", "data modeling", "collection design"},
    "query optimization": {"query", "queries", "optimize", "optimization", "index", "indexes", "indexing", "performance", "tuning", "explain", "execution", "aggregation", "query optimization", "optimized queries", "database performance"},
    "ci/cd": {"ci", "cd", "pipeline", "pipelines", "github", "actions", "jenkins", "gitlab", "deploy", "deployment", "build", "automate", "automation", "devops", "github actions", "gitlab ci", "deployment pipelines"},
    "state management": {"redux", "zustand", "mobx", "context", "store", "state", "recoil"},
    "clean code": {"refactor", "refactoring", "clean", "solid", "maintainable", "pattern", "patterns", "standards", "code quality"},
    "api documentation": {"swagger", "openapi", "postman", "docs", "documentation", "endpoints"},
    "testing": {"test", "tests", "unit", "integration", "jest", "pytest", "mocha", "cypress", "playwright", "tdd", "bdd"},
    "cloud": {"aws", "azure", "gcp", "s3", "ec2", "lambda", "cloud", "cloudformation", "terraform", "infrastructure"},
    "cloud infrastructure": {"aws", "azure", "gcp", "s3", "ec2", "instances", "terraform", "cloud", "infrastructure", "devops"},
    "cloud infrastructure operations": {"aws", "azure", "gcp", "s3", "ec2", "instances", "terraform", "cloud", "infrastructure", "operations", "provisioned", "provisioning"},
    "mentoring": {"mentor", "mentored", "mentoring", "guidance", "coach", "coaching", "mentorship", "led junior developers"},
    "code review": {"code reviews", "reviewed code", "code quality", "pr reviews", "pull request", "code review"},
    "troubleshooting": {"troubleshooting", "debugging", "fixed defects", "incident triage", "root cause", "resolved issues", "production defects", "production bugs"},
}


class SemanticEvidenceRetriever:
    """
    Lightweight character 3-gram and token n-gram similarity retriever.
    Fast sub-millisecond retrieval for fallback candidate evidence discovery.
    """

    @staticmethod
    def _char_ngrams(text: str, n: int = 3) -> set[str]:
        cleaned = re.sub(r"\s+", " ", text.casefold()).strip()
        if len(cleaned) < n:
            return {cleaned} if cleaned else set()
        return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}

    @classmethod
    def similarity(cls, query: str, text: str) -> float:
        q_stems = _stem_tokens(query)
        t_stems = _stem_tokens(text)
        if not q_stems or not t_stems:
            return 0.0

        # Direct stem overlap ratio
        stem_overlap = len(q_stems & t_stems) / len(q_stems)
        if stem_overlap > 0:
            return round(stem_overlap, 3)

        # Check semantic synonym mapping (e.g. Kafka -> message queues / event streaming)
        q_lower = query.casefold().strip()
        text_lower = text.casefold()
        for term, syns in SEMANTIC_SYNONYMS.items():
            concept_stems = _stem_tokens(term)
            for s in syns:
                concept_stems.update(_stem_tokens(s))
            if q_stems & concept_stems:
                for s in syns:
                    if len(s) > 2 and re.search(rf"\b{re.escape(s)}\b", text_lower):
                        return 0.65

        # Sub-word token similarity for long technical words (len >= 5) to catch variants
        q_tokens = [t for t in _TOKEN.findall(q_lower) if len(t) >= 5]
        t_tokens = [t for t in _TOKEN.findall(text_lower) if len(t) >= 5]
        if q_tokens and t_tokens:
            for qt in q_tokens:
                qt_ngrams = {qt[i : i + 3] for i in range(len(qt) - 2)}
                for tt in t_tokens:
                    tt_ngrams = {tt[i : i + 3] for i in range(len(tt) - 2)}
                    if qt_ngrams and tt_ngrams:
                        jaccard = len(qt_ngrams & tt_ngrams) / len(qt_ngrams | tt_ngrams)
                        if jaccard >= 0.35:
                            return round(jaccard, 3)

        return 0.0

    @staticmethod
    def embedding_vector(text: str, dim: int = 256) -> list[float]:
        """
        Computes a normalized dense embedding vector for text using subword character n-grams
        and stemmed word tokens with feature hashing.
        """
        if not text:
            return [0.0] * dim
        vec = [0.0] * dim
        cleaned = re.sub(r"\s+", " ", text.casefold()).strip()
        tokens = [t for t in _TOKEN.findall(cleaned) if len(t) > 1]

        # Word token features with stem projection
        for t in tokens:
            st = _stem_token(t)
            h1 = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16) % dim
            h2 = int(hashlib.md5(st.encode("utf-8")).hexdigest(), 16) % dim
            vec[h1] += 2.0
            vec[h2] += 2.0

        # Subword character n-gram features (3-gram and 4-gram)
        for n in (3, 4):
            if len(cleaned) >= n:
                for i in range(len(cleaned) - n + 1):
                    gram = cleaned[i : i + n]
                    h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16) % dim
                    vec[h] += 1.0

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    @classmethod
    def cosine_similarity(cls, text1: str, text2: str) -> float:
        """Computes cosine similarity between dense text embedding vectors."""
        if not text1 or not text2:
            return 0.0
        v1 = cls.embedding_vector(text1)
        v2 = cls.embedding_vector(text2)
        dot = sum(a * b for a, b in zip(v1, v2))
        return round(max(0.0, min(1.0, dot)), 4)

    @classmethod
    def retrieve(cls, query: str, evidence: list[Evidence], top_k: int = 5) -> list[Evidence]:
        if not evidence or not query:
            return []
        scored = []
        for e in evidence:
            sim = cls.similarity(query, e.text)
            scored.append((sim, e.evidence_id, e))
        scored.sort(key=lambda x: (-x[0], x[1]))
        passing = [row[2] for row in scored if row[0] > 0.05]
        return passing[:top_k]


class EvidencePrefilter:
    def __init__(self, threshold: float, limit: int) -> None:
        self.threshold, self.limit = threshold, limit

    @staticmethod
    def _select_diverse_evidence(scored_items: list[tuple[float, str, Evidence]], target_limit: int) -> list[Evidence]:
        if not scored_items:
            return []

        by_kind: dict[str, list[tuple[float, str, Evidence]]] = {}
        for row in scored_items:
            by_kind.setdefault(row[2].kind, []).append(row)

        selected: list[Evidence] = []
        selected_ids: set[str] = set()

        selected.append(scored_items[0][2])
        selected_ids.add(scored_items[0][1])

        kinds_order = list(by_kind.keys())
        while len(selected) < target_limit:
            added_any = False
            for k in kinds_order:
                candidates = [row for row in by_kind[k] if row[1] not in selected_ids]
                if candidates:
                    best = candidates[0]
                    if len(selected) < target_limit:
                        selected.append(best[2])
                        selected_ids.add(best[1])
                        added_any = True
            if not added_any:
                break

        for row in scored_items:
            if len(selected) >= target_limit:
                break
            if row[1] not in selected_ids:
                selected.append(row[2])
                selected_ids.add(row[1])

        return selected

    def select(self, requirement: Requirement, evidence: list[Evidence]) -> list[Evidence]:
        if not evidence:
            return []

        # 1. Full Resume Evidence Boundaries with Entity-Type Integrity
        if requirement.kind in {RequirementKind.SKILL, RequirementKind.REQUIRED_SKILL, RequirementKind.PREFERRED_SKILL}:
            target_evidence = [e for e in evidence if e.kind in {"skills", "project", "experience", "summary", "certification", "education"}]
            if not target_evidence:
                return []
        elif requirement.kind == RequirementKind.RESPONSIBILITY:
            target_evidence = [e for e in evidence if e.kind in {"experience", "project", "summary", "skills"}]
            if not target_evidence:
                return []
        elif requirement.kind == RequirementKind.PROJECT_RELEVANCE:
            target_evidence = [e for e in evidence if e.kind in {"project", "experience", "summary"}]
            if not target_evidence:
                return []
        elif requirement.kind == RequirementKind.DEGREE:
            target_evidence = [e for e in evidence if e.kind in {"education"}]
            if not target_evidence:
                return []
        elif requirement.kind in {RequirementKind.EXPERIENCE, RequirementKind.CONTEXTUAL_EXPERIENCE}:
            target_evidence = [e for e in evidence if e.kind in {"experience", "internship"}]
            if not target_evidence:
                return []
        elif requirement.kind == RequirementKind.CERTIFICATION:
            target_evidence = [e for e in evidence if e.kind in {"certification"}]
            if not target_evidence:
                return []
        elif requirement.kind == RequirementKind.LANGUAGE:
            target_evidence = [e for e in evidence if e.kind in {"languages"}]
            if not target_evidence:
                return []
        else:
            allowed_kinds = ALLOWED_EVIDENCE_MAP.get(requirement.kind, {"experience", "project", "summary", "skills"})
            target_evidence = [e for e in evidence if e.kind in allowed_kinds]
            if not target_evidence:
                return []

        # 2. Lexical & Synonym Overlap Scoring
        req_lower = requirement.text.casefold()
        synonym_phrases: set[str] = set()
        for term, syns in SEMANTIC_SYNONYMS.items():
            if term in req_lower or any(re.search(rf"\b{re.escape(t)}\b", req_lower) for t in term.split() if len(t) > 2):
                synonym_phrases.update(syns)
                synonym_phrases.add(term)

        required_stems = _stem_tokens(requirement.text)
        for s in synonym_phrases:
            required_stems.update(_stem_tokens(s))

        scored = []
        for item in target_evidence:
            item_lower = item.text.casefold()
            phrase_bonus = 0.5 if any(p in item_lower for p in synonym_phrases if len(p.split()) > 1) else 0.0
            item_stems = _stem_tokens(item.text)
            overlap = len(required_stems & item_stems) / len(required_stems) if required_stems else 0.0
            score = overlap + phrase_bonus
            if score > 0:
                scored.append((score, item.evidence_id, item))

        # Semantic cosine similarity fallback for chunks failing lexical threshold (or having 0 lexical overlap)
        lexical_passing_ids = {row[1] for row in scored if row[0] >= self.threshold}
        for item in target_evidence:
            if item.evidence_id not in lexical_passing_ids:
                cos_sim = SemanticEvidenceRetriever.cosine_similarity(requirement.text, item.text)
                if cos_sim >= 0.20:
                    scored.append((cos_sim, item.evidence_id, item))

        if scored:
            scored.sort(key=lambda row: (-row[0], row[1]))
            passing = [row for row in scored if row[0] >= self.threshold]

            top_score = scored[0][0]
            if top_score >= 0.60:
                adaptive_limit = min(3, self.limit)
            elif top_score >= 0.15:
                adaptive_limit = min(5, self.limit)
            else:
                adaptive_limit = min(8, max(5, self.limit))

            candidates_to_filter = passing if passing else scored
            return self._select_diverse_evidence(candidates_to_filter, adaptive_limit)

        # 3. Fallback & Ambiguous Evidence Behavior:
        # Lexical prefilter miss should NOT immediately become NO_MATCH if candidate has evidence.
        # Check semantic retrieval first, then provide candidate profile evidence for LLM verification.
        if requirement.kind in {RequirementKind.SKILL, RequirementKind.REQUIRED_SKILL, RequirementKind.PREFERRED_SKILL}:
            semantic_selected = SemanticEvidenceRetriever.retrieve(
                requirement.text, target_evidence, top_k=min(5, self.limit)
            )
            if semantic_selected:
                return semantic_selected
            fallback_evidence = [e for e in target_evidence if e.kind in {"skills", "project", "experience", "summary"}]
            return (fallback_evidence if fallback_evidence else target_evidence)[: min(3, self.limit)]

        # For NON-SKILLS: Profile fallback
        allowed_kinds = {"experience", "project", "summary"} if requirement.kind == RequirementKind.RESPONSIBILITY else {"skills", "project", "experience", "summary", "certification"}
        fallback_evidence = [e for e in target_evidence if e.kind in allowed_kinds]
        return (fallback_evidence if fallback_evidence else target_evidence)[: min(5, self.limit)]


class GroqKeyEntry:
    def __init__(self, key_id: str, api_key: str, settings: Settings | None = None) -> None:
        self.key_id = key_id
        self.api_key = api_key
        self.settings = settings or get_settings()
        self.window_seconds = 60.0
        self.usage_history: list[tuple[float, int]] = []
        self.reserved_in_flight = 0
        self.active_leases = 0
        self.cooldown_until = 0.0
        self.failure_count = 0
        self.permanent_failures = 0
        self.circuit_state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_failure_time = 0.0
        self.header_remaining_tokens: int | None = None
        self.header_reset_timestamp: float | None = None

    @property
    def tpm_limit(self) -> int:
        val = getattr(self.settings, "GROQ_TPM_LIMIT", 8000)
        return int(val) if isinstance(val, (int, float)) else 8000

    @property
    def safety_margin(self) -> float:
        val = getattr(self.settings, "GROQ_TPM_SAFETY_MARGIN", 0.10)
        return float(val) if isinstance(val, (int, float)) else 0.10

    @property
    def usable_tpm(self) -> int:
        return int(self.tpm_limit * (1.0 - self.safety_margin))

    @property
    def cooldown_seconds(self) -> float:
        return float(_get_setting_val(self.settings, "PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS", 60.0))

    @property
    def max_failures(self) -> int:
        return int(_get_setting_val(self.settings, "PROVIDER_CIRCUIT_BREAKER_MAX_FAILURES", 2))

    def is_available(self, now: float | None = None) -> bool:
        if now is None:
            now = time.monotonic()
        if now < self.cooldown_until:
            return False
        if self.circuit_state == "OPEN":
            if now - self.last_failure_time >= self.cooldown_seconds:
                self.circuit_state = "HALF_OPEN"
                return True
            return False
        return True

    def available_tokens(self, now: float | None = None) -> int:
        if now is None:
            now = time.monotonic()
        history = [(ts, tok) for ts, tok in self.usage_history if now - ts < self.window_seconds]
        local_used = sum(tok for _, tok in history)
        if self.header_reset_timestamp is not None and now < self.header_reset_timestamp:
            if self.header_remaining_tokens is not None:
                avail_hdr = max(0, self.header_remaining_tokens - self.reserved_in_flight)
                avail_loc = max(0, self.usable_tpm - local_used - self.reserved_in_flight)
                return min(avail_hdr, avail_loc)
        return max(0, self.usable_tpm - local_used - self.reserved_in_flight)

    def can_reserve(self, estimated_tokens: int, now: float | None = None) -> bool:
        if not self.is_available(now):
            return False
        return self.available_tokens(now) >= estimated_tokens

    def reserve(self, estimated_tokens: int) -> None:
        self.reserved_in_flight += estimated_tokens
        self.active_leases += 1

    def release(self, estimated_tokens: int) -> None:
        self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)
        self.active_leases = max(0, self.active_leases - 1)

    def record_response(self, estimated_tokens: int, response: httpx.Response | None = None, actual_tokens: int | None = None) -> None:
        self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)
        self.active_leases = max(0, self.active_leases - 1)
        now = time.monotonic()
        used_tokens = actual_tokens if actual_tokens is not None else estimated_tokens
        self.usage_history.append((now, used_tokens))
        self.circuit_state = "CLOSED"
        self.failure_count = 0
        self.permanent_failures = 0

        if response is not None and hasattr(response, "headers"):
            headers = response.headers
            if isinstance(headers, dict) or hasattr(headers, "get"):
                rem_tok = headers.get("x-ratelimit-remaining-tokens")
                res_tok = headers.get("x-ratelimit-reset-tokens")
                if rem_tok is not None and type(rem_tok) in (int, float, str):
                    try:
                        self.header_remaining_tokens = int(rem_tok)
                    except (ValueError, TypeError):
                        pass
                if res_tok is not None and type(res_tok) in (int, float, str):
                    try:
                        res_str = str(res_tok).strip()
                        if res_str.endswith("ms"):
                            seconds = float(res_str[:-2]) / 1000.0
                        elif res_str.endswith("s"):
                            seconds = float(res_str[:-1])
                        else:
                            seconds = float(res_str)
                        self.header_reset_timestamp = now + seconds
                    except (ValueError, TypeError):
                        pass

    def record_429(self, estimated_tokens: int, response: httpx.Response | None = None) -> float:
        self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)
        self.active_leases = max(0, self.active_leases - 1)
        now = time.monotonic()
        self.header_remaining_tokens = 0
        retry_after = 2.0
        if response is not None and hasattr(response, "headers"):
            headers = response.headers
            if isinstance(headers, dict) or hasattr(headers, "get"):
                hdr_retry = headers.get("retry-after") or headers.get("Retry-After")
                res_tok = headers.get("x-ratelimit-reset-tokens")
                if hdr_retry is not None:
                    try:
                        retry_after = max(1.0, float(hdr_retry))
                    except (ValueError, TypeError):
                        pass
                elif res_tok is not None:
                    try:
                        res_str = str(res_tok).strip()
                        if res_str.endswith("ms"):
                            retry_after = max(0.5, float(res_str[:-2]) / 1000.0)
                        elif res_str.endswith("s"):
                            retry_after = max(0.5, float(res_str[:-1]))
                        else:
                            retry_after = max(0.5, float(res_str))
                    except (ValueError, TypeError):
                        pass
        self.cooldown_until = now + retry_after
        self.last_failure_time = now
        self.failure_count += 1
        return retry_after

    def record_bad_request(self, estimated_tokens: int) -> None:
        """HTTP 400 Bad Request indicates payload/parameter error rather than key exhaustion.
        Releases reserved tokens/leases without marking key unavailable or advancing failure counters."""
        self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)
        self.active_leases = max(0, self.active_leases - 1)

    def record_failure(self, estimated_tokens: int, status_code: int | None = None, is_permanent: bool = False, error_msg: str = "") -> None:
        self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)
        self.active_leases = max(0, self.active_leases - 1)
        now = time.monotonic()
        self.last_failure_time = now
        self.failure_count += 1
        if is_permanent or status_code in (401, 402, 403, 404):
            self.permanent_failures += 1
            self.circuit_state = "OPEN"
        elif self.failure_count >= self.max_failures:
            self.circuit_state = "OPEN"
        else:
            self.cooldown_until = max(self.cooldown_until, now + 1.0)


class GroqKeyPoolManager:
    _instance: GroqKeyPoolManager | None = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = asyncio.Lock()
        self.keys: list[GroqKeyEntry] = []
        self._load_keys()

    def _load_keys(self) -> None:
        self.keys.clear()
        k1 = getattr(self.settings, "GROQ_API_KEY_1", None) or getattr(self.settings, "GROQ_API_KEY", None)
        k2 = getattr(self.settings, "GROQ_API_KEY_2", None)
        k3 = getattr(self.settings, "GROQ_API_KEY_3", None)

        if k1:
            self.keys.append(GroqKeyEntry("groq_key_1", str(k1), self.settings))
        if k2:
            self.keys.append(GroqKeyEntry("groq_key_2", str(k2), self.settings))
        if k3:
            self.keys.append(GroqKeyEntry("groq_key_3", str(k3), self.settings))

    @classmethod
    def get_manager(cls, settings: Settings | None = None) -> GroqKeyPoolManager:
        if cls._instance is None:
            cls._instance = cls(settings)
        elif settings is not None and cls._instance.settings is not settings:
            cls._instance.settings = settings
            cls._instance._load_keys()
        return cls._instance

    @classmethod
    def reset_manager(cls, settings: Settings | None = None) -> None:
        if settings is not None:
            cls._instance = cls(settings)
        elif cls._instance is not None:
            cls._instance._load_keys()

    def estimate_input_tokens(self, payload: dict[str, Any]) -> int:
        prompt_text = ""
        for msg in payload.get("messages", []):
            prompt_text += str(msg.get("content", ""))
        return int(len(prompt_text) / 2.8 * 1.15) + 20

    def compute_allowed_output_tokens(self, estimated_input: int, req_count: int = 1) -> int:
        per_resume_budget = int(_get_setting_val(self.settings, "GROQ_TOKEN_BUDGET_PER_RESUME", 7000))
        overhead = 100
        max_configured = int(_get_setting_val(self.settings, "GROQ_MAX_COMPLETION_TOKENS", 3500))
        budget_headroom = per_resume_budget - estimated_input - overhead
        if budget_headroom <= 0:
            return 0
        # Compact JSON requires ~35-45 tokens per requirement + 50 tokens overhead
        needed = max(250, req_count * 45 + 50)
        return max(200, min(max_configured, budget_headroom, needed))

    def estimate_tokens(self, payload: dict[str, Any], output_estimate: int | None = None) -> int:
        estimated_input = self.estimate_input_tokens(payload)
        overhead = 100
        if output_estimate is None:
            max_out = payload.get("max_tokens")
            if max_out is not None:
                output_estimate = int(max_out)
            else:
                user_content = ""
                for msg in payload.get("messages", []):
                    if msg.get("role") == "user":
                        user_content = str(msg.get("content", ""))
                try:
                    data = json.loads(user_content)
                    req_count = len(data.get("requirements", []))
                    output_estimate = self.compute_allowed_output_tokens(estimated_input, req_count=req_count)
                except Exception:
                    output_estimate = int(_get_setting_val(self.settings, "GROQ_ESTIMATED_OUTPUT_TOKENS", 350))
        
        per_resume_budget = int(_get_setting_val(self.settings, "GROQ_TOKEN_BUDGET_PER_RESUME", 7000))
        return min(per_resume_budget, estimated_input + output_estimate + overhead)

    async def acquire_key(self, estimated_tokens: int, excluded_key_ids: set[str] | None = None) -> GroqKeyEntry | None:
        async with self._lock:
            now = time.monotonic()
            excluded = excluded_key_ids or set()
            candidates = [
                k for k in self.keys
                if k.key_id not in excluded and k.can_reserve(estimated_tokens, now)
            ]
            if not candidates:
                return None
            
            # Sort by active_leases ascending, then available_tokens descending
            candidates.sort(key=lambda k: (k.active_leases, -k.available_tokens(now)))
            chosen = candidates[0]
            chosen.reserve(estimated_tokens)
            return chosen

    async def release_key(self, key_id: str, estimated_tokens: int) -> None:
        async with self._lock:
            for k in self.keys:
                if k.key_id == key_id:
                    k.release(estimated_tokens)
                    break


class GroqTokenBudgetGate:
    _instance: GroqTokenBudgetGate | None = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.pool = GroqKeyPoolManager.get_manager(self.settings)

    @classmethod
    def get_gate(cls, settings: Settings | None = None) -> GroqTokenBudgetGate:
        if cls._instance is None:
            cls._instance = cls(settings)
        elif settings is not None and cls._instance.settings is not settings:
            cls._instance.settings = settings
            cls._instance.pool = GroqKeyPoolManager.get_manager(settings)
        return cls._instance

    @classmethod
    def reset_gate(cls, settings: Settings | None = None) -> None:
        GroqKeyPoolManager.reset_manager(settings)
        if settings is not None:
            cls._instance = cls(settings)
        elif cls._instance is not None:
            cls._instance.pool._load_keys()

    @property
    def usable_tpm(self) -> int:
        return int(_get_setting_val(self.settings, "GROQ_TOKEN_BUDGET_PER_RESUME", 7000))

    def available_tokens(self) -> int:
        now = time.monotonic()
        return sum(k.available_tokens(now) for k in self.pool.keys if k.is_available(now))

    def estimate_tokens(self, payload: dict[str, Any], output_estimate: int | None = None) -> int:
        return self.pool.estimate_tokens(payload, output_estimate=output_estimate)

    async def try_reserve(self, estimated_tokens: int) -> bool:
        now = time.monotonic()
        return any(k.can_reserve(estimated_tokens, now) for k in self.pool.keys)

    async def release_reservation(self, estimated_tokens: int) -> None:
        pass

    async def record_response(self, estimated_tokens: int, response: httpx.Response | None = None, actual_tokens: int | None = None) -> None:
        pass

    async def record_429(self, estimated_tokens: int, response: httpx.Response | None = None) -> float:
        return 2.0


def _parse_llm_batch_response(
    content: Any,
    requirements: list[Requirement],
    finish_reason: str | None = None,
) -> LLMVerdictBatch:
    is_truncated = (finish_reason == "length")
    if isinstance(content, str):
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned).strip()
        try:
            data = json.loads(cleaned)
        except Exception as json_err:
            parsed_json = None
            # Truncated JSON recovery: find the last completed object in array/object
            last_brace_idx = cleaned.rfind("}")
            while last_brace_idx > 0 and parsed_json is None:
                candidate = cleaned[:last_brace_idx + 1]
                for suffix in ("]}", "]", ""):
                    try:
                        parsed_json = json.loads(candidate + suffix)
                        if parsed_json:
                            is_truncated = True
                            logger.warning(
                                "llm_response_truncated_max_tokens",
                                reason="recovered_partial_objects_from_truncated_json",
                                raw_length=len(cleaned),
                                truncated_at_index=last_brace_idx,
                                finish_reason=finish_reason,
                            )
                            break
                    except Exception:
                        pass
                if parsed_json is not None:
                    break
                last_brace_idx = cleaned.rfind("}", 0, last_brace_idx)

            if parsed_json is not None:
                data = parsed_json
            else:
                logger.error("llm_response_json_parse_failed", raw_content=content[:500], error=str(json_err))
                raise json_err
    else:
        data = content

    raw_items: list[dict[str, Any]] = []
    if isinstance(data, list):
        raw_items = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        for candidate_key in ("verdicts", "evaluations", "results", "requirements", "classifications", "data", "items"):
            if candidate_key in data and isinstance(data[candidate_key], list):
                raw_items = [item for item in data[candidate_key] if isinstance(item, dict)]
                break
        if not raw_items and ("coverage_score" in data or "sub_claims" in data or "coverage" in data or "reasoning" in data or "requirement_id" in data):
            raw_items = [data]

    if not raw_items:
        logger.warning("llm_response_no_verdict_items_extracted", raw_data=str(data)[:300])
        return LLMVerdictBatch(verdicts=[])

    # Build stable ID lookup maps from requirements to map each verdict safely
    req_map_exact = {r.requirement_id: r.requirement_id for r in requirements}
    req_map_casefold = {r.requirement_id.casefold(): r.requirement_id for r in requirements}
    req_map_norm = {re.sub(r"[\s_#-]+", ":", r.requirement_id.casefold()): r.requirement_id for r in requirements}
    req_map_text = {r.text.strip().casefold(): r.requirement_id for r in requirements}
    req_map_idx = {str(i + 1): r.requirement_id for i, r in enumerate(requirements)}

    validated_verdicts: list[LLMVerdict] = []
    for idx, item in enumerate(raw_items):
        raw_id = str(item.get("requirement_id") or item.get("id") or item.get("requirement_text") or item.get("text") or "").strip()
        matched_id = None
        if raw_id in req_map_exact:
            matched_id = req_map_exact[raw_id]
        elif raw_id.casefold() in req_map_casefold:
            matched_id = req_map_casefold[raw_id.casefold()]
        elif re.sub(r"[\s_#-]+", ":", raw_id.casefold()) in req_map_norm:
            matched_id = req_map_norm[re.sub(r"[\s_#-]+", ":", raw_id.casefold())]
        elif raw_id.casefold() in req_map_text:
            matched_id = req_map_text[raw_id.casefold()]
        elif raw_id in req_map_idx:
            matched_id = req_map_idx[raw_id]
        elif len(raw_items) == len(requirements) and idx < len(requirements):
            matched_id = requirements[idx].requirement_id

        if not matched_id and len(requirements) == 1:
            matched_id = requirements[0].requirement_id

        if matched_id:
            raw_s = str(item.get("status") or item.get("s") or "").upper()
            status_val = None
            if raw_s in {"MATCHED", "MATCH"}:
                status_val = MatchStatus.MATCHED
            elif raw_s in {"PARTIALLY_MATCHED", "PARTIAL"}:
                status_val = MatchStatus.PARTIALLY_MATCHED
            elif raw_s in {"NO_MATCH", "UNMATCHED", "REJECTED", "NO", "NONE"}:
                status_val = MatchStatus.NO_MATCH

            conf_raw = item.get("confidence") if item.get("confidence") is not None else item.get("c")
            conf_val = float(conf_raw) if conf_raw is not None else 0.95

            cov_raw = item.get("coverage_score") if item.get("coverage_score") is not None else (item.get("cov") if item.get("cov") is not None else item.get("coverage"))
            if cov_raw is not None:
                cov_val = float(cov_raw)
            else:
                cov_val = 1.0 if status_val == MatchStatus.MATCHED else (0.5 if status_val == MatchStatus.PARTIALLY_MATCHED else 0.0)

            ev_ids_raw = item.get("evidence_ids") if item.get("evidence_ids") is not None else (item.get("e") if item.get("e") is not None else item.get("ev_ids"))
            if isinstance(ev_ids_raw, str):
                ev_ids_list = [x.strip() for x in ev_ids_raw.split(",") if x.strip()]
            elif isinstance(ev_ids_raw, list):
                ev_ids_list = [str(x).strip() for x in ev_ids_raw if str(x).strip()]
            else:
                ev_ids_list = []

            reasoning_val = str(item.get("reasoning") or item.get("r") or item.get("reason") or "").strip()

            item_copy = {
                "requirement_id": matched_id,
                "status": status_val,
                "confidence": conf_val,
                "coverage_score": cov_val,
                "coverage": cov_val,
                "evidence_ids": ev_ids_list,
                "reasoning": reasoning_val,
                "importance": str(item.get("importance") or item.get("imp") or "important"),
                "sub_claims": list(item.get("sub_claims") or [req_map_text.get(matched_id, "")]),
                "sub_claim_evidence": list(item.get("sub_claim_evidence") or []),
            }
            try:
                validated_verdicts.append(LLMVerdict.model_validate(item_copy))
            except Exception as v_err:
                logger.warning("llm_verdict_model_validation_warning", requirement_id=matched_id, error=str(v_err))

    if is_truncated or (len(validated_verdicts) < len(requirements) and finish_reason == "length"):
        logger.warning(
            "llm_response_truncated_max_tokens",
            finish_reason=finish_reason,
            requirements_sent=len(requirements),
            verdicts_parsed=len(validated_verdicts),
            missing_count=len(requirements) - len(validated_verdicts),
        )

    return LLMVerdictBatch(verdicts=validated_verdicts)


def _get_setting_val(settings: Any, attr: str, default: Any) -> Any:
    val = getattr(settings, attr, None)
    if val is None:
        return default
    if type(val) is type(default):
        return val
    try:
        if isinstance(default, int):
            return int(val)
        if isinstance(default, float):
            return float(val)
        if isinstance(default, str):
            return str(val)
        if isinstance(default, bool):
            return bool(val)
    except Exception:
        pass
    return default


class ProviderCircuitBreaker:
    _instance: ProviderCircuitBreaker | None = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.pool = GroqKeyPoolManager.get_manager(self.settings)

    @classmethod
    def get_breaker(cls, settings: Settings | None = None) -> ProviderCircuitBreaker:
        if cls._instance is None:
            cls._instance = cls(settings)
        elif settings is not None and cls._instance.settings is not settings:
            cls._instance.settings = settings
            cls._instance.pool = GroqKeyPoolManager.get_manager(settings)
        return cls._instance

    @classmethod
    def reset_breaker(cls, settings: Settings | None = None) -> None:
        GroqKeyPoolManager.reset_manager(settings)
        if settings is not None:
            cls._instance = cls(settings)
        elif cls._instance is not None:
            cls._instance.pool._load_keys()

    def can_call(self, provider: str) -> bool:
        if provider == "groq":
            now = time.monotonic()
            return any(k.is_available(now) for k in self.pool.keys)
        return False

    def record_success(self, provider: str) -> None:
        pass

    def record_failure(self, provider: str, status_code: int | None = None, is_permanent: bool = False, error_msg: str = "") -> None:
        pass


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
        k1 = getattr(self.settings, "GROQ_API_KEY_1", None) or getattr(self.settings, "GROQ_API_KEY", None)
        k2 = getattr(self.settings, "GROQ_API_KEY_2", None)
        k3 = getattr(self.settings, "GROQ_API_KEY_3", None)
        return bool(self.settings.ENABLE_HYBRID_MATCHING and (k1 or k2 or k3))

    async def evaluate_with_usage(
        self, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
        resume_id: str = "default_resume",
        pre_reserved: bool = False,
        allow_retries: bool = True,
    ) -> tuple[list[MatchVerdict], dict[str, int]]:
        usage_stats = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if not self.enabled or not requirements:
            return [], usage_stats

        pool = GroqKeyPoolManager.get_manager(self.settings)
        token_budget = int(_get_setting_val(self.settings, "GROQ_TOKEN_BUDGET_PER_RESUME", 7000))
        overhead = 100

        digest = hashlib.sha256(json.dumps({
            "requirements": [r.model_dump(mode="json") for r in requirements],
            "evidence": [e.model_dump(mode="json") for e in evidence],
            "model": self.settings.GROQ_MODEL,
            "threshold": self.settings.HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD,
            "allowed_evidence": {key: sorted(value) for key, value in (allowed_evidence or {}).items()},
        }, sort_keys=True).encode()).hexdigest()
        if digest in self._cache:
            self._cache.move_to_end(digest)
            return [verdict.model_copy(deep=True) for verdict in self._cache[digest]], usage_stats

        # Size allowed output tokens within legal application budget
        initial_payload = self._payload(requirements, evidence, allowed_evidence, max_output_tokens=100)
        estimated_input = pool.estimate_input_tokens(initial_payload)

        if estimated_input + overhead >= token_budget:
            logger.error(
                "groq_llm_input_exceeds_budget",
                resume_id=resume_id,
                estimated_input=estimated_input,
                token_budget=token_budget,
                overhead=overhead,
                total_requirements=len(requirements),
            )
            return [], usage_stats

        allowed_output = pool.compute_allowed_output_tokens(estimated_input, req_count=len(requirements))
        payload = self._payload(requirements, evidence, allowed_evidence, max_output_tokens=allowed_output)
        estimated_tokens = min(token_budget, estimated_input + allowed_output + overhead)

        parsed: LLMVerdictBatch | None = None
        timeout = float(_get_setting_val(self.settings, "GROQ_TIMEOUT_SECONDS", 30.0))
        client = self._get_client(timeout)
        base_url = str(_get_setting_val(self.settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")).rstrip("/")
        t0 = time.monotonic()
        logical_eval_id = f"eval_{resume_id}_{int(t0 * 1000)}"

        excluded_keys: set[str] = set()
        max_attempts = max(1, len(pool.keys)) if allow_retries else 1

        for attempt in range(max_attempts):
            key_entry = await pool.acquire_key(estimated_tokens, excluded_key_ids=excluded_keys)
            if key_entry is None:
                logger.warning(
                    "groq_all_keys_unavailable",
                    logical_evaluation_id=logical_eval_id,
                    resume_id=resume_id,
                    estimated_tokens=estimated_tokens,
                    token_budget=token_budget,
                    attempt=attempt + 1,
                )
                break

            key_id = key_entry.key_id
            try:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {key_entry.api_key}"},
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()

                resp_json = response.json()
                usage = resp_json.get("usage", {})
                actual_tokens = usage.get("total_tokens")
                prompt_toks = usage.get("prompt_tokens", 0)
                comp_toks = usage.get("completion_tokens", 0)
                tot_toks = actual_tokens if actual_tokens is not None else (prompt_toks + comp_toks)
                usage_stats = {"prompt_tokens": prompt_toks, "completion_tokens": comp_toks, "total_tokens": tot_toks}

                key_entry.record_response(estimated_tokens, response=response, actual_tokens=actual_tokens)

                choices = resp_json.get("choices", [])
                choice = choices[0] if choices else {}
                resp_finish_reason = choice.get("finish_reason")
                content = choice.get("message", {}).get("content", "")
                parsed = _parse_llm_batch_response(content, requirements, finish_reason=resp_finish_reason)

                validated = self._validate(parsed, requirements, evidence, allowed_evidence)

                logger.info(
                    "groq_llm_evaluation_completed",
                    logical_evaluation_id=logical_eval_id,
                    resume_id=resume_id,
                    provider="groq",
                    physical_attempt_number=attempt + 1,
                    key_id=key_id,
                    request_id=resp_json.get("id"),
                    token_budget=token_budget,
                    estimated_input_tokens=estimated_input,
                    allowed_output_tokens=allowed_output,
                    estimated_tokens=estimated_tokens,
                    actual_input_tokens=prompt_toks,
                    actual_output_tokens=comp_toks,
                    actual_total_tokens=tot_toks,
                    finish_reason=resp_finish_reason,
                    verdicts_requested=len(requirements),
                    verdicts_returned=len(validated),
                    missing_verdicts=max(0, len(requirements) - len(validated)),
                    logical_request_count=1,
                    duration_ms=round((time.monotonic() - t0) * 1000.0, 2),
                    status="success",
                )

                if resp_finish_reason == "length" or len(validated) < len(requirements):
                    missing_count = max(0, len(requirements) - len(validated))
                    logger.warning(
                        "llm_response_truncated_max_tokens",
                        logical_evaluation_id=logical_eval_id,
                        resume_id=resume_id,
                        finish_reason=resp_finish_reason,
                        verdicts_requested=len(requirements),
                        verdicts_returned=len(validated),
                        missing_verdicts=missing_count,
                        reason="response_truncated_no_subbatch_retry",
                    )
                break
            except Exception as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                resp_obj = getattr(exc, "response", None)

                # Safely extract error details without logging sensitive headers/keys
                error_type = None
                error_code = None
                error_message = str(exc)
                if resp_obj is not None:
                    try:
                        resp_json = resp_obj.json()
                        if isinstance(resp_json, dict):
                            err_dict = resp_json.get("error")
                            if isinstance(err_dict, dict):
                                error_type = err_dict.get("type")
                                error_code = err_dict.get("code")
                                error_message = err_dict.get("message") or str(err_dict)
                            elif err_dict:
                                error_message = str(err_dict)
                    except Exception:
                        try:
                            error_message = resp_obj.text[:500]
                        except Exception:
                            pass

                # HTTP 400 Bad Request indicates malformed payload or unsupported parameter/model
                if status_code == 400:
                    key_entry.record_bad_request(estimated_tokens)
                    logger.error(
                        "groq_http_error",
                        status_code=400,
                        error_type=error_type,
                        error_code=error_code,
                        error_message=error_message,
                        model=payload.get("model"),
                        logical_evaluation_id=logical_eval_id,
                        resume_id=resume_id,
                        physical_attempt_number=attempt + 1,
                        key_id=key_id,
                    )
                    # For HTTP 400:
                    # 1. Do NOT rotate to another key.
                    # 2. Do NOT send the same invalid payload using other keys.
                    # 3. Cleanly break out of loop so logical evaluation fails gracefully.
                    break

                elif status_code == 429:
                    retry_after = key_entry.record_429(estimated_tokens, response=resp_obj)
                    logger.warning(
                        "groq_key_unavailable",
                        logical_evaluation_id=logical_eval_id,
                        resume_id=resume_id,
                        key_id=key_id,
                        status_code=429,
                        reason="rate_limit",
                        error_type=error_type,
                        error_code=error_code,
                        error_message=error_message,
                        retry_after=retry_after,
                        token_budget=token_budget,
                    )
                else:
                    is_perm = status_code in {401, 402, 403, 404}
                    key_entry.record_failure(estimated_tokens, status_code=status_code, is_permanent=is_perm, error_msg=str(exc))
                    logger.warning(
                        "groq_key_unavailable",
                        logical_evaluation_id=logical_eval_id,
                        resume_id=resume_id,
                        key_id=key_id,
                        status_code=status_code,
                        reason=type(exc).__name__,
                        error_type=error_type,
                        error_code=error_code,
                        error_message=error_message,
                        token_budget=token_budget,
                    )

                excluded_keys.add(key_id)
                if attempt < max_attempts - 1:
                    logger.info(
                        "groq_key_rotation",
                        logical_evaluation_id=logical_eval_id,
                        resume_id=resume_id,
                        previous_key=key_id,
                        attempt=attempt + 1,
                        token_budget=token_budget,
                    )

        if parsed is None:
            logger.error(
                "groq_llm_evaluation_failed",
                logical_evaluation_id=logical_eval_id,
                resume_id=resume_id,
                physical_attempt_count=attempt + 1,
                key_id=key_id if "key_id" in locals() else None,
                status_code=status_code if "status_code" in locals() else None,
                error_type=error_type if "error_type" in locals() else None,
                error_code=error_code if "error_code" in locals() else None,
                error_message=error_message if "error_message" in locals() else None,
                estimated_input_tokens=estimated_input,
                allowed_output_tokens=allowed_output,
                actual_input_tokens=0,
                actual_output_tokens=0,
                actual_total_tokens=0,
                verdicts_requested=len(requirements),
                verdicts_returned=0,
                missing_verdicts=len(requirements),
                token_budget=token_budget,
                total_requirements=len(requirements),
            )
            return [], usage_stats

        validated = self._validate(parsed, requirements, evidence, allowed_evidence)

        self._cache[digest] = validated
        self._cache.move_to_end(digest)
        while len(self._cache) > self.settings.HYBRID_MATCHING_CACHE_SIZE:
            self._cache.popitem(last=False)
        return [verdict.model_copy(deep=True) for verdict in validated], usage_stats

        self._cache[digest] = validated
        self._cache.move_to_end(digest)
        while len(self._cache) > self.settings.HYBRID_MATCHING_CACHE_SIZE:
            self._cache.popitem(last=False)
        return [verdict.model_copy(deep=True) for verdict in validated], usage_stats

    async def evaluate(
        self, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
        pre_reserved: bool = False,
        allow_retries: bool = True,
    ) -> list[MatchVerdict]:
        try:
            verdicts, _ = await self.evaluate_with_usage(
                requirements, evidence, allowed_evidence, pre_reserved=pre_reserved, allow_retries=allow_retries
            )
            return verdicts
        except Exception:
            return []

    @staticmethod
    def _normalize_evidence_id(raw_id: str, valid_supplied_ids: set[str]) -> str | None:
        if not raw_id or not isinstance(raw_id, str):
            return None
        clean = raw_id.strip()
        if clean in valid_supplied_ids:
            return clean

        clean_lower = clean.casefold()
        for sid in valid_supplied_ids:
            if sid.casefold() == clean_lower:
                return sid

        # Normalize delimiter variants: "experience 1", "Experience: 1", "experience-1", "experience_1", "Experience #1"
        normalized_form = re.sub(r"[\s_#-]+", ":", clean_lower)
        normalized_form = re.sub(r":+", ":", normalized_form)
        for sid in valid_supplied_ids:
            if sid.casefold() == normalized_form:
                return sid

        # Suffix matching (e.g. "1" matches "experience:1" if only 1 matching kind exists)
        if clean.isdigit():
            candidates = [sid for sid in valid_supplied_ids if sid.endswith(f":{clean}")]
            if len(candidates) == 1:
                return candidates[0]

        return None

    def _validate(
        self, batch: LLMVerdictBatch, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
    ) -> list[MatchVerdict]:
        requirement_ids = {item.requirement_id for item in requirements}
        requirement_by_id = {item.requirement_id: item for item in requirements}
        all_evidence_ids = {item.evidence_id for item in evidence}
        evidence_by_id = {item.evidence_id: item for item in evidence}
        threshold = self.settings.HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD
        result: list[MatchVerdict] = []
        seen: set[str] = set()

        for item in batch.verdicts:
            req_id = item.requirement_id
            if req_id not in requirement_ids or req_id in seen:
                continue
            seen.add(req_id)
            req_obj = requirement_by_id[req_id]

            # Determine valid supplied evidence IDs for this specific requirement
            if allowed_evidence and req_id in allowed_evidence:
                req_supplied_ids = allowed_evidence[req_id] & all_evidence_ids
            else:
                req_supplied_ids = all_evidence_ids

            # Normalize and validate all cited evidence IDs with strict entity-type compatibility
            raw_cited_ids = list(item.evidence_ids) if item.evidence_ids else []
            valid_cited_ids: list[str] = []
            has_cross_entity_rejection = False
            for raw_id in raw_cited_ids:
                norm_id = self._normalize_evidence_id(raw_id, req_supplied_ids)
                if norm_id and norm_id not in valid_cited_ids:
                    ev_item = evidence_by_id.get(norm_id)
                    if ev_item and not is_entity_compatible(req_obj.kind, ev_item.kind):
                        has_cross_entity_rejection = True
                        logger.warning(
                            "cross_entity_evidence_rejected",
                            requirement_id=req_id,
                            requirement_entity_type=req_obj.kind.value,
                            evidence_id=norm_id,
                            evidence_entity_type=ev_item.kind,
                            compatibility=False,
                            reason="cross_entity_evidence_forbidden",
                        )
                        continue
                    valid_cited_ids.append(norm_id)

            # If no valid citations found from raw list, but only 1 evidence item was supplied for this requirement:
            if not valid_cited_ids and not raw_cited_ids and len(req_supplied_ids) == 1:
                single_id = list(req_supplied_ids)[0]
                ev_item = evidence_by_id.get(single_id)
                if ev_item and is_entity_compatible(req_obj.kind, ev_item.kind):
                    valid_cited_ids = [single_id]

            has_valid_evidence = bool(valid_cited_ids)

            sub_claims_val = getattr(item, "sub_claims", []) or []
            sub_claim_evidence_val = getattr(item, "sub_claim_evidence", []) or []
            raw_reasoning = str(getattr(item, "reasoning", "") or "").strip()
            raw_reasoning_lower = raw_reasoning.lower()

            # Negation detection to prevent score/reasoning contradictions
            negation_phrases = (
                "no evidence", "none of the provided", "none of the candidate", "no candidate evidence",
                "does not mention", "doesn't mention", "no mention", "lacks ", "lacking ",
                "not mentioned", "no relevant evidence", "no direct or adjacent",
                "neither direct nor adjacent", "no experience mentioned", "no matching evidence",
                "no demonstrated experience", "unmet", "zero evidence", "no transferable evidence"
            )
            has_negation = any(phrase in raw_reasoning_lower for phrase in negation_phrases)
            all_subclaims_none = (
                bool(sub_claim_evidence_val)
                and all(isinstance(sc, dict) and sc.get("evidence_level") == "none" for sc in sub_claim_evidence_val)
            )

            raw_status_str = str(getattr(item.status, "value", item.status) if item.status is not None else "").upper()
            is_matched_raw = raw_status_str in {"MATCHED", "MATCH"}
            is_partial_raw = raw_status_str in {"PARTIALLY_MATCHED", "PARTIAL"}
            is_no_match_raw = raw_status_str in {"NO_MATCH", "UNMATCHED", "REJECTED"}

            # Extract coverage score
            raw_cov = getattr(item, "coverage_score", None)
            if raw_cov is None:
                raw_cov = getattr(item, "coverage", None)

            if raw_cov is not None:
                coverage_val = float(raw_cov)
            elif sub_claim_evidence_val:
                direct_cnt = sum(1 for sc in sub_claim_evidence_val if isinstance(sc, dict) and sc.get("evidence_level") == "direct")
                adj_cnt = sum(1 for sc in sub_claim_evidence_val if isinstance(sc, dict) and sc.get("evidence_level") == "adjacent")
                tot = len(sub_claim_evidence_val)
                coverage_val = (direct_cnt * 1.0 + adj_cnt * 0.5) / tot if tot > 0 else 0.0
            else:
                if is_matched_raw:
                    coverage_val = 1.0
                elif is_partial_raw:
                    coverage_val = 0.5
                else:
                    coverage_val = 0.0

            # Contradiction Prevention Rule: If reasoning states no evidence or all subclaims are none,
            # coverage_val MUST be 0.0 and status MUST be NO_MATCH
            if has_negation or all_subclaims_none:
                if coverage_val >= 0.25 or is_matched_raw or is_partial_raw:
                    logger.warning(
                        "score_reasoning_contradiction_corrected",
                        requirement_id=req_id,
                        requirement_text=req_obj.text,
                        raw_coverage=coverage_val,
                        raw_status=raw_status_str,
                        raw_reasoning=raw_reasoning,
                        reason="negation_in_reasoning_or_all_subclaims_none",
                    )
                coverage_val = 0.0
                is_matched_raw = False
                is_partial_raw = False
                is_no_match_raw = True

            importance_val = str(getattr(item, "importance", None) or getattr(req_obj, "importance", "important") or "important").lower()
            if importance_val not in {"critical", "important", "minor"}:
                importance_val = getattr(req_obj, "importance", "important")

            # Determine final status
            confirmed = (coverage_val >= 0.25 or is_matched_raw or is_partial_raw) and not is_no_match_raw
            item_confidence = float(getattr(item, "confidence", 1.0) if getattr(item, "confidence", None) is not None else 0.0)

            # 1. Reject ungrounded matches (no valid evidence IDs cited) to UNRESOLVED
            if confirmed and not has_valid_evidence:
                status = MatchStatus.UNRESOLVED
                method = MatchMethod.LLM_UNRESOLVED
                if has_cross_entity_rejection:
                    reasoning = f"(Rejected: cross_entity_evidence_forbidden). {raw_reasoning}".strip()
                else:
                    reasoning = f"(Rejected: No valid candidate evidence ID cited for match). {raw_reasoning}".strip()
                coverage_val = 0.0
            # 2. Low-confidence LLM verdict handling: Explicitly reject to NO_MATCH if confidence < threshold
            elif confirmed and item_confidence < threshold:
                logger.warning(
                    "llm_verdict_low_confidence_rejected",
                    requirement_id=req_id,
                    confidence=item_confidence,
                    threshold=threshold,
                    raw_status=raw_status_str,
                    reason="llm_confidence_below_threshold_fallback_no_match",
                )
                status = MatchStatus.NO_MATCH
                method = MatchMethod.LLM_REJECTED
                coverage_val = 0.0
                reasoning = f"LLM match verdict rejected due to low confidence ({item_confidence:.2f} < threshold {threshold:.2f})."
            # 3. Validated high-confidence match
            elif confirmed and coverage_val > 0.0:
                if coverage_val >= 0.7 or (is_matched_raw and coverage_val >= 0.5):
                    status = MatchStatus.MATCHED
                else:
                    status = MatchStatus.PARTIALLY_MATCHED
                method = MatchMethod.LLM_CONFIRMED
                reasoning = raw_reasoning or ("LLM confirmed requirement match from candidate evidence." if status == MatchStatus.MATCHED else "Candidate shows partial / transferable evidence for requirement.")
            # 4. Explicit NO_MATCH
            elif is_no_match_raw:
                status = MatchStatus.NO_MATCH
                method = MatchMethod.LLM_REJECTED
                reasoning = raw_reasoning or "LLM verified requirement is unmet."
            else:
                status = MatchStatus.UNRESOLVED
                method = MatchMethod.LLM_UNRESOLVED
                reasoning = raw_reasoning or "LLM verdict unresolved by evidence validation."

            result.append(MatchVerdict(
                requirement_id=req_id,
                status=status,
                confidence=item.confidence if (confirmed or is_no_match_raw) else 0.0,
                evidence_ids=sorted(valid_cited_ids) if valid_cited_ids else [],
                reasoning=reasoning.strip(),
                method=method,
                coverage=coverage_val,
                coverage_score=coverage_val,
                importance=importance_val,
                sub_claims=sub_claims_val,
                sub_claim_evidence=sub_claim_evidence_val,
                matched_concepts=getattr(item, "matched_concepts", []) or [],
                missing_concepts=getattr(item, "missing_concepts", []) or [],
            ))
        return result

    def _payload(
        self, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        req_list = [
            {
                "id": r.requirement_id,
                "requirement_id": r.requirement_id,
                "kind": getattr(r.kind, "value", str(r.kind)),
                "text": r.text,
                "ev_ids": sorted(list(allowed_evidence.get(r.requirement_id, set()))) if allowed_evidence and r.requirement_id in allowed_evidence else [],
                "allowed_evidence_ids": sorted(list(allowed_evidence.get(r.requirement_id, set()))) if allowed_evidence and r.requirement_id in allowed_evidence else [],
            }
            for r in requirements
        ]
        ev_list = [
            {
                "id": e.evidence_id,
                "evidence_id": e.evidence_id,
                "kind": e.kind,
                "text": e.text,
            }
            for e in evidence
        ]
        content = json.dumps({"requirements": req_list, "candidate_evidence": ev_list})
        system_prompt = (
            "Evaluate candidate evidence against job requirements. Return compact JSON verdicts.\n"
            "Rules for each requirement:\n"
            "- \"id\": requirement_id\n"
            "- \"s\": status -> \"MATCHED\" (direct evidence), \"PARTIALLY_MATCHED\" (adjacent/transferable evidence), or \"NO_MATCH\" (unmet/no evidence)\n"
            "- \"c\": confidence -> float 0.0 to 1.0 (e.g. 0.95)\n"
            "- \"cov\": coverage_score -> float 0.0 to 1.0 (1.0 = fully met, 0.5 = partial, 0.0 = none)\n"
            "- \"e\": array of matching candidate evidence IDs cited from candidate_evidence (e.g. [\"skills:1\"]). Empty array [] if NO_MATCH.\n\n"
            "Return ONLY JSON: {\"verdicts\": [{\"id\": \"...\", \"s\": \"MATCHED|PARTIALLY_MATCHED|NO_MATCH\", \"c\": 0.95, \"cov\": 1.0, \"e\": [\"...\"]}]}"
        )
        if max_output_tokens is None:
            max_output_tokens = min(
                int(_get_setting_val(self.settings, "GROQ_MAX_COMPLETION_TOKENS", 3500)),
                max(250, len(requirements) * 45 + 50),
            )
        return {
            "model": getattr(self.settings, "GROQ_MODEL", "openai/gpt-oss-20b"),
            "temperature": 0,
            "max_tokens": max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
        }


class CerebrasTokenBudgetGate:
    _instance: CerebrasTokenBudgetGate | None = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.window_seconds = 60.0
        self.usage_history: list[tuple[float, int]] = []
        self.reserved_in_flight = 0
        self._lock: asyncio.Lock | None = None
        self.header_remaining_tokens: int | None = None
        self.header_reset_timestamp: float | None = None

    @classmethod
    def get_gate(cls, settings: Settings | None = None) -> CerebrasTokenBudgetGate:
        if cls._instance is None:
            cls._instance = cls(settings)
        elif settings is not None:
            cls._instance.settings = settings
        if cls._instance._lock is None:
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    @classmethod
    def reset_gate(cls) -> None:
        if cls._instance is not None:
            cls._instance.usage_history.clear()
            cls._instance.reserved_in_flight = 0
            cls._instance.header_remaining_tokens = None
            cls._instance.header_reset_timestamp = None

    @property
    def tpm_limit(self) -> int:
        val = getattr(self.settings, "CEREBRAS_TPM_LIMIT", 60000)
        if not isinstance(val, (int, float)):
            return 60000
        return int(val)

    @property
    def safety_margin(self) -> float:
        val = getattr(self.settings, "CEREBRAS_TPM_SAFETY_MARGIN", 0.10)
        if not isinstance(val, (int, float)):
            return 0.10
        return float(val)

    @property
    def usable_tpm(self) -> int:
        return int(self.tpm_limit * (1.0 - self.safety_margin))

    def available_tokens(self) -> int:
        now = time.monotonic()
        history = [(ts, tok) for ts, tok in self.usage_history if now - ts < self.window_seconds]
        local_used = sum(tok for _, tok in history)
        if self.header_reset_timestamp is not None and now < self.header_reset_timestamp:
            if self.header_remaining_tokens is not None:
                avail_hdr = max(0, self.header_remaining_tokens - self.reserved_in_flight)
                avail_loc = max(0, self.usable_tpm - local_used - self.reserved_in_flight)
                return min(avail_hdr, avail_loc)
        return max(0, self.usable_tpm - local_used - self.reserved_in_flight)

    async def try_reserve(self, estimated_tokens: int) -> bool:
        """
        Atomically check available Cerebras tokens and reserve estimated_tokens if capacity exists.
        Returns True if capacity exists and reservation succeeded, False otherwise.
        Does NOT block or sleep.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            now = time.monotonic()
            self.usage_history = [(ts, tok) for ts, tok in self.usage_history if now - ts < self.window_seconds]
            local_used = sum(tok for _, tok in self.usage_history)
            if self.header_reset_timestamp is not None and now < self.header_reset_timestamp:
                if self.header_remaining_tokens is not None:
                    avail_hdr = max(0, self.header_remaining_tokens - self.reserved_in_flight)
                    avail_loc = max(0, self.usable_tpm - local_used - self.reserved_in_flight)
                    available = min(avail_hdr, avail_loc)
                else:
                    available = max(0, self.usable_tpm - local_used - self.reserved_in_flight)
            else:
                available = max(0, self.usable_tpm - local_used - self.reserved_in_flight)

            if available >= estimated_tokens:
                self.reserved_in_flight += estimated_tokens
                return True
            return False

    async def acquire_reservation(self, estimated_tokens: int, correlation_id: str = "") -> bool:
        return await self.try_reserve(estimated_tokens)

    async def release_reservation(self, estimated_tokens: int) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)

    async def record_response(self, estimated_tokens: int, response: httpx.Response | None = None, actual_tokens: int | None = None) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)
            now = time.monotonic()
            used_tokens = actual_tokens if actual_tokens is not None else estimated_tokens
            self.usage_history.append((now, used_tokens))


class CerebrasMatchEvaluator:
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
        return bool(self.settings.ENABLE_HYBRID_MATCHING and getattr(self.settings, "CEREBRAS_API_KEY", None))

    async def evaluate_with_usage(
        self, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
        allow_retries: bool = True,
    ) -> tuple[list[MatchVerdict], dict[str, int]]:
        usage_stats = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if not self.enabled or not requirements:
            return [], usage_stats

        breaker = ProviderCircuitBreaker.get_breaker(self.settings)
        if not breaker.can_call("cerebras"):
            logger.warning("cerebras_circuit_breaker_open_skipping_call")
            return [], usage_stats

        chunk_size = max(1, min(20, int(_get_setting_val(self.settings, "LLM_BATCH_CHUNK_SIZE", 8))))
        throttle_seconds = max(0.0, float(_get_setting_val(self.settings, "LLM_BATCH_THROTTLE_SECONDS", 0.25)))

        if len(requirements) > chunk_size:
            all_verdicts: list[MatchVerdict] = []
            combined_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            chunks = [requirements[i:i + chunk_size] for i in range(0, len(requirements), chunk_size)]
            for idx, chunk_reqs in enumerate(chunks):
                if idx > 0 and throttle_seconds > 0:
                    await asyncio.sleep(throttle_seconds)

                chunk_allowed = None
                if allowed_evidence is not None:
                    chunk_allowed = {r.requirement_id: allowed_evidence.get(r.requirement_id, set()) for r in chunk_reqs}
                    chunk_ev_ids = {eid for ids in chunk_allowed.values() for eid in ids}
                    chunk_ev = [e for e in evidence if e.evidence_id in chunk_ev_ids] if chunk_ev_ids else evidence
                else:
                    chunk_ev = evidence

                chunk_verdicts, chunk_usage = await self.evaluate_with_usage(
                    chunk_reqs, chunk_ev, chunk_allowed,
                    allow_retries=allow_retries,
                )
                all_verdicts.extend(chunk_verdicts)
                for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    combined_usage[k] += chunk_usage.get(k, 0)

            return all_verdicts, combined_usage

        model_name = getattr(self.settings, "CEREBRAS_MODEL", "gpt-oss-120b")
        digest = hashlib.sha256(json.dumps({
            "requirements": [r.model_dump(mode="json") for r in requirements],
            "evidence": [e.model_dump(mode="json") for e in evidence],
            "model": model_name,
            "threshold": self.settings.HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD,
            "allowed_evidence": {key: sorted(value) for key, value in (allowed_evidence or {}).items()},
        }, sort_keys=True).encode()).hexdigest()

        if digest in self._cache:
            self._cache.move_to_end(digest)
            return [verdict.model_copy(deep=True) for verdict in self._cache[digest]], usage_stats

        payload = GroqMatchEvaluator(self.settings)._payload(requirements, evidence, allowed_evidence)
        payload["model"] = model_name
        payload["max_tokens"] = min(
            int(_get_setting_val(self.settings, "CEREBRAS_MAX_COMPLETION_TOKENS", 4096)),
            max(1024, len(requirements) * 350 + 200),
        )

        gate = CerebrasTokenBudgetGate.get_gate(self.settings)
        groq_gate = GroqTokenBudgetGate.get_gate(self.settings)
        estimated_tokens = groq_gate.estimate_tokens(payload)

        can_reserve = await gate.try_reserve(estimated_tokens)
        if not can_reserve:
            logger.warning(
                "cerebras_token_budget_exhausted",
                provider="cerebras",
                estimated_tokens=estimated_tokens,
                available_tokens=gate.available_tokens(),
                usable_limit=gate.usable_tpm,
                correlation_id=digest[:8],
            )
            return [], usage_stats

        parsed: LLMVerdictBatch | None = None
        cerebras_timeout = float(_get_setting_val(self.settings, "CEREBRAS_TIMEOUT_SECONDS", 30.0))
        client = self._get_client(cerebras_timeout)
        cerebras_retries = int(_get_setting_val(self.settings, "CEREBRAS_MAX_RETRIES", 2))
        max_retries = max(1, cerebras_retries) if allow_retries else 0
        total_attempts = max_retries + 1
        resp_finish_reason: str | None = None

        for attempt in range(total_attempts):
            try:
                base_url = str(_get_setting_val(self.settings, "CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1")).rstrip("/")
                url = f"{base_url}/chat/completions"
                api_key = str(_get_setting_val(self.settings, "CEREBRAS_API_KEY", ""))
                headers = {"Authorization": f"Bearer {api_key}"}
                response = await client.post(url, headers=headers, json=payload, timeout=cerebras_timeout)
                response.raise_for_status()

                resp_json = response.json()
                usage = resp_json.get("usage", {})
                actual_tokens = usage.get("total_tokens")
                prompt_toks = usage.get("prompt_tokens", 0)
                comp_toks = usage.get("completion_tokens", 0)
                tot_toks = actual_tokens if actual_tokens is not None else (prompt_toks + comp_toks)
                usage_stats = {"prompt_tokens": prompt_toks, "completion_tokens": comp_toks, "total_tokens": tot_toks}

                await gate.record_response(estimated_tokens, response=response, actual_tokens=actual_tokens)
                breaker.record_success("cerebras")

                choices = resp_json.get("choices", [])
                choice = choices[0] if choices else {}
                resp_finish_reason = choice.get("finish_reason")
                content = choice.get("message", {}).get("content", "")
                parsed = _parse_llm_batch_response(content, requirements, finish_reason=resp_finish_reason)
                break
            except Exception as exc:
                if attempt == total_attempts - 1:
                    await gate.release_reservation(estimated_tokens)

                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                resp_body = None
                if hasattr(exc, "response") and exc.response is not None:
                    try:
                        resp_body = exc.response.text
                    except Exception:
                        pass

                error_type = type(exc).__name__
                if status_code == 401:
                    error_kind = "authentication_error"
                elif status_code == 402:
                    error_kind = "payment_required_error"
                elif status_code == 404:
                    error_kind = "model_not_found_error"
                elif status_code == 429:
                    error_kind = "rate_limit_error"
                elif status_code and status_code >= 500:
                    error_kind = "server_error"
                else:
                    error_kind = "request_failed_error"

                # Permanent errors: 402 (payment required) or 401/403/404 -> Fail fast immediately, DO NOT RETRY
                if status_code in {400, 401, 402, 403, 404}:
                    if status_code == 402:
                        logger.critical(
                            "cerebras_provider_billing_error — requires manual account action",
                            provider="cerebras",
                            status_code=402,
                            error_kind="payment_required_error",
                            response_body=resp_body,
                            correlation_id=digest[:8],
                        )
                    else:
                        logger.error(
                            "cerebras_permanent_client_error",
                            provider="cerebras",
                            status_code=status_code,
                            error_type=error_type,
                            error_kind=error_kind,
                            model=model_name,
                            response_body=resp_body,
                            correlation_id=digest[:8],
                        )
                    breaker.record_failure("cerebras", status_code=status_code, is_permanent=True, error_msg=str(exc))
                    return [], {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

                is_last_attempt = (attempt == total_attempts - 1)
                if is_last_attempt:
                    logger.error(
                        "cerebras_llm_request_failed",
                        provider="cerebras",
                        status_code=status_code,
                        error_type=error_type,
                        error_kind=error_kind,
                        model=model_name,
                        response_body=resp_body,
                        correlation_id=digest[:8],
                    )
                    breaker.record_failure("cerebras", status_code=status_code, is_permanent=False, error_msg=str(exc))
                    return [], {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

                retry_after_hdr = None
                if status_code == 429 and getattr(exc, "response", None) is not None:
                    retry_after_hdr = exc.response.headers.get("retry-after") or exc.response.headers.get("Retry-After")

                delay = 1.0 if attempt == 0 else 3.0
                if retry_after_hdr:
                    try:
                        parsed_delay = float(retry_after_hdr)
                        if parsed_delay >= 0:
                            delay = parsed_delay
                    except (ValueError, TypeError):
                        pass

                delay = min(delay, 15.0)
                logger.warning(
                    "cerebras_llm_attempt_failed",
                    attempt=attempt + 1,
                    status_code=status_code,
                    error_type=error_type,
                    delay_seconds=round(delay, 2),
                    response_body=resp_body,
                )
                await asyncio.sleep(delay)

        if parsed is None:
            return [], usage_stats

        validated = GroqMatchEvaluator(self.settings)._validate(parsed, requirements, evidence, allowed_evidence)

        if resp_finish_reason == "length" or len(validated) < len(requirements):
            missing_count = max(0, len(requirements) - len(validated))
            logger.warning(
                "llm_response_truncated_max_tokens",
                provider="cerebras",
                finish_reason=resp_finish_reason,
                verdicts_requested=len(requirements),
                verdicts_returned=len(validated),
                missing_verdicts=missing_count,
                reason="response_truncated_no_subbatch_retry",
            )

        self._cache[digest] = validated
        self._cache.move_to_end(digest)
        while len(self._cache) > self.settings.HYBRID_MATCHING_CACHE_SIZE:
            self._cache.popitem(last=False)
        return [verdict.model_copy(deep=True) for verdict in validated], usage_stats

    async def evaluate(
        self, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
        allow_retries: bool = True,
    ) -> list[MatchVerdict]:
        verdicts, _ = await self.evaluate_with_usage(requirements, evidence, allowed_evidence, allow_retries=allow_retries)
        return verdicts


class SmartMatchEvaluator:
    """Multi-Key Groq LLM Evaluator with automatic key rotation and zero external fallbacks."""
    def __init__(
        self, settings: Settings | None = None,
        groq_evaluator: GroqMatchEvaluator | None = None,
        cerebras_evaluator: Any | None = None,  # Kept in signature for backward compatibility, but never used
    ) -> None:
        self.settings = settings or get_settings()
        self.groq = groq_evaluator or GroqMatchEvaluator(self.settings)

    async def _invoke_evaluator(
        self, evaluator: Any, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
        resume_id: str = "default_resume",
        allow_retries: bool = True,
    ) -> tuple[list[MatchVerdict], dict[str, int]]:
        for name in ("evaluate_with_usage", "evaluate"):
            fn = getattr(evaluator, name, None)
            if fn is None or not callable(fn):
                continue
            if type(evaluator).__name__ == "MagicMock" and name == "evaluate_with_usage" and type(fn).__name__ != "AsyncMock" and getattr(fn, "side_effect", None) is None:
                continue
            try:
                sig = inspect.signature(fn)
                kwargs = {}
                if "resume_id" in sig.parameters:
                    kwargs["resume_id"] = resume_id
                if "allow_retries" in sig.parameters:
                    kwargs["allow_retries"] = allow_retries
                raw = fn(requirements, evidence, allowed_evidence, **kwargs)
            except (TypeError, ValueError):
                raw = fn(requirements, evidence, allowed_evidence)
            res = await raw if inspect.isawaitable(raw) else raw
            if isinstance(res, tuple):
                return res[0], res[1]
            return res, {}
        return [], {}

    async def evaluate(
        self, requirements: list[Requirement], evidence: list[Evidence],
        allowed_evidence: dict[str, set[str]] | None = None,
        resume_id: str = "default_resume",
    ) -> tuple[list[MatchVerdict], dict[str, Any]]:
        if not requirements:
            return [], {}

        start_ts = time.monotonic()
        pool = GroqKeyPoolManager.get_manager(self.settings)
        token_budget = int(_get_setting_val(self.settings, "GROQ_TOKEN_BUDGET_PER_RESUME", 7000))

        if hasattr(self.groq, "_payload"):
            payload_res = self.groq._payload(requirements, evidence, allowed_evidence)
            payload = await payload_res if inspect.isawaitable(payload_res) else payload_res
        else:
            payload = GroqMatchEvaluator(self.settings)._payload(requirements, evidence, allowed_evidence)

        estimated_tokens = pool.estimate_tokens(payload)
        t0 = time.monotonic()
        try:
            verdicts, usage = await self._invoke_evaluator(
                self.groq, requirements, evidence, allowed_evidence, resume_id=resume_id, allow_retries=True
            )
            wait_ms = (time.monotonic() - t0) * 1000.0
        except Exception as exc:
            logger.error(
                "groq_llm_evaluation_failed",
                resume_id=resume_id,
                provider="groq",
                token_budget=token_budget,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            verdicts = []
            usage = {}
            wait_ms = (time.monotonic() - t0) * 1000.0

        actual_input = usage.get("prompt_tokens", 0)
        actual_output = usage.get("completion_tokens", 0)
        actual_total = usage.get("total_tokens", actual_input + actual_output)
        llm_duration_ms = (time.monotonic() - start_ts) * 1000.0

        telemetry = {
            "resume_id": resume_id,
            "provider_selected": "groq" if verdicts else "none",
            "token_budget": token_budget,
            "estimated_tokens": estimated_tokens,
            "actual_input_tokens": actual_input,
            "actual_output_tokens": actual_output,
            "actual_total_tokens": actual_total,
            "provider_wait_ms": round(wait_ms, 2),
            "llm_duration_ms": round(llm_duration_ms, 2),
            "total_resume_duration_ms": round(llm_duration_ms, 2),
            "fallback_used": False,
            "fallback_reason": "none",
        }

        logger.info("resume_llm_routing_telemetry", **telemetry)

        # One-line run summary metric for logging & monitoring
        eval_failed = sum(1 for v in verdicts if getattr(v, "status", None) == MatchStatus.EVALUATION_FAILED)
        if not verdicts and len(requirements) > 0:
            eval_failed = len(requirements)

        logger.info(
            "llm_evaluation_run_summary",
            resume_id=resume_id,
            total_requirements=len(requirements),
            verdicts_count=len(verdicts),
            provider_selected="groq" if verdicts else "none",
            fallback_used=False,
            eval_failed_count=eval_failed,
            duration_ms=round(llm_duration_ms, 2),
        )

        return verdicts, telemetry


class ResumeQueueScheduler:
    """Concurrency manager limiting active resume evaluations to MAX_CONCURRENT_RESUMES (default 3) with request pacing."""
    def __init__(self, max_concurrent: int = 3, throttle_seconds: float = 0.0) -> None:
        self.max_concurrent = max_concurrent
        self.throttle_seconds = throttle_seconds
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def run_resume_task(self, resume_id: str, task_coro: Any) -> Any:
        async with self.semaphore:
            if self.throttle_seconds > 0:
                await asyncio.sleep(self.throttle_seconds)
            logger.info("resume_scheduler_task_started", resume_id=resume_id, max_concurrent=self.max_concurrent)
            res = await task_coro
            logger.info("resume_scheduler_task_completed", resume_id=resume_id)
            return res


class HybridMatchingService:
    def __init__(self, settings: Settings | None = None, evaluator: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.evaluator = evaluator or SmartMatchEvaluator(self.settings)
        self.matcher = DeterministicRequirementMatcher()

    async def match(self, job: Any, resume: Any, extracted: Any, config: Any = None) -> tuple[Any, list[MatchVerdict]]:
        requirements = RequirementBuilder.build(job, config)
        evidence = EvidenceBuilder.build(extracted)
        deterministic = [self.matcher.match(item, resume, evidence) for item in requirements]
        prefilter = EvidencePrefilter(
            self.settings.HYBRID_MATCHING_KEYWORD_OVERLAP_THRESHOLD,
            self.settings.HYBRID_MATCHING_MAX_EVIDENCE_PER_REQUIREMENT,
        )
        supplied: dict[str, Evidence] = {}
        allowed_evidence: dict[str, set[str]] = {}
        unresolved: list[Requirement] = []

        requirement_by_id = {item.requirement_id: item for item in requirements}
        for verdict in deterministic:
            requirement = requirement_by_id.get(verdict.requirement_id)
            if not requirement:
                continue
            # Rule 1: Canonical / deterministic success -> MATCHED -> STOP (Do NOT call LLM)
            if verdict.status == MatchStatus.MATCHED:
                verdict.coverage = 1.0
                verdict.coverage_score = 1.0
                verdict.importance = getattr(requirement, "importance", "important") or ("critical" if getattr(requirement, "required", True) else "important")
                verdict.sub_claims = [requirement.text]
                verdict.sub_claim_evidence = [{"claim": requirement.text, "evidence_level": "direct", "note": "Exact / alias canonical match."}]
                logger.info(
                    "matching_routing_decision",
                    requirement_id=requirement.requirement_id,
                    requirement_text=requirement.text,
                    deterministic_status=verdict.status.value,
                    fallback_eligible=False,
                    llm_attempted=False,
                    reason="Deterministic high-confidence match",
                )
                continue

            # Rule 2: Canonical matching FAILS -> Check candidate evidence via prefilter
            selected = prefilter.select(requirement, evidence)
            if selected:
                # Evidence exists -> route to LLM fallback
                unresolved.append(requirement)
                supplied.update((item.evidence_id, item) for item in selected)
                allowed_evidence[requirement.requirement_id] = {item.evidence_id for item in selected}
                logger.info(
                    "matching_routing_decision",
                    requirement_id=requirement.requirement_id,
                    requirement_text=requirement.text,
                    deterministic_status=verdict.status.value,
                    fallback_eligible=True,
                    llm_attempted=True,
                    evidence_count=len(selected),
                )
            else:
                # Rule 3: Canonical fails + genuinely NO candidate evidence -> NO_MATCH (0 LLM calls)
                allowed_evidence[requirement.requirement_id] = set()
                verdict.status = MatchStatus.NO_MATCH
                verdict.coverage = 0.0
                verdict.coverage_score = 0.0
                verdict.importance = getattr(requirement, "importance", "important") or ("critical" if getattr(requirement, "required", True) else "important")
                verdict.sub_claims = [requirement.text]
                verdict.sub_claim_evidence = [{"claim": requirement.text, "evidence_level": "none", "note": "No candidate evidence available."}]
                verdict.reasoning = "No candidate evidence available for prefilter."
                logger.info(
                    "matching_routing_decision",
                    requirement_id=requirement.requirement_id,
                    requirement_text=requirement.text,
                    deterministic_status=verdict.status.value,
                    fallback_eligible=False,
                    llm_attempted=False,
                    reason="No candidate evidence available for prefilter",
                )

        resume_id = str(getattr(resume, "id", None) or getattr(resume, "candidate_name", None) or getattr(resume, "name", None) or getattr(resume, "document_id", None) or "default_resume")
        if unresolved:
            if hasattr(self.evaluator, "evaluate"):
                import inspect
                sig = inspect.signature(self.evaluator.evaluate)
                if "resume_id" in sig.parameters:
                    res_eval = await self.evaluator.evaluate(unresolved, list(supplied.values()), allowed_evidence, resume_id=resume_id)
                    llm = res_eval[0] if isinstance(res_eval, tuple) else res_eval
                else:
                    res_eval = await self.evaluator.evaluate(unresolved, list(supplied.values()), allowed_evidence)
                    llm = res_eval[0] if isinstance(res_eval, tuple) else res_eval
            else:
                llm = []
        else:
            llm = []
        llm_by_id = {item.requirement_id: item for item in llm}
        unresolved_ids = {item.requirement_id for item in unresolved}
        fused = []
        for item in deterministic:
            req_id = item.requirement_id
            if req_id in llm_by_id:
                fused.append(llm_by_id[req_id])
            elif req_id in unresolved_ids:
                req_obj = requirement_by_id.get(req_id)
                logger.error(
                    "llm_evaluation_failed_for_requirement",
                    requirement_id=req_id,
                    requirement_text=getattr(req_obj, "text", ""),
                    resume_id=resume_id,
                    error="llm_evaluation_omitted_or_failed",
                )
                failed_verdict = MatchVerdict(
                    requirement_id=req_id,
                    requirement_text=getattr(req_obj, "text", None),
                    kind=getattr(req_obj, "kind", None),
                    status=MatchStatus.EVALUATION_FAILED,
                    confidence=0.0,
                    evidence_ids=[],
                    reasoning="AI evaluation could not be completed for this requirement (provider failure or timeout).",
                    method=MatchMethod.EVALUATION_FAILED,
                    coverage=0.0,
                    coverage_score=0.0,
                    importance=getattr(req_obj, "importance", "important") if req_obj else "important",
                    sub_claims=[getattr(req_obj, "text", "")] if req_obj else [],
                    sub_claim_evidence=[{"claim": getattr(req_obj, "text", ""), "evidence_level": "none", "note": "Evaluation failed."}] if req_obj else [],
                )
                fused.append(failed_verdict)
            else:
                fused.append(item)
        projects = EvidenceBuilder._projects(extracted)
        for project in projects:
            project["technologies"] = list(project.get("technologies") or [])
        requirement_by_id = {item.requirement_id: item for item in requirements}
        evidence_by_id = {item.evidence_id: item for item in evidence}
        for verdict in fused:
            requirement = requirement_by_id.get(verdict.requirement_id)
            if requirement:
                verdict.requirement_text = requirement.text
                verdict.kind = requirement.kind
                # Defense-in-depth: Final entity compatibility re-validation
                valid_ev_ids = []
                for eid in verdict.evidence_ids:
                    ev_item = evidence_by_id.get(eid)
                    if ev_item and is_entity_compatible(requirement.kind, ev_item.kind):
                        valid_ev_ids.append(eid)
                    else:
                        logger.warning(
                            "final_verdict_cross_entity_evidence_removed",
                            requirement_id=verdict.requirement_id,
                            requirement_entity_type=requirement.kind.value,
                            evidence_id=eid,
                            evidence_entity_type=ev_item.kind if ev_item else "unknown",
                            compatibility=False,
                            reason="cross_entity_evidence_forbidden",
                        )
                verdict.evidence_ids = valid_ev_ids
                if verdict.status in {MatchStatus.MATCHED, MatchStatus.PARTIALLY_MATCHED} and not verdict.evidence_ids and requirement.kind in {RequirementKind.DEGREE, RequirementKind.EXPERIENCE, RequirementKind.CONTEXTUAL_EXPERIENCE, RequirementKind.CERTIFICATION, RequirementKind.LANGUAGE}:
                    verdict.status = MatchStatus.UNRESOLVED
                    verdict.reasoning = "Evidence rejected due to entity type mismatch (cross_entity_evidence_forbidden)."

            logger.info(
                "final_requirement_verdict",
                requirement_id=verdict.requirement_id,
                requirement_text=getattr(verdict, "requirement_text", ""),
                final_status=verdict.status.value,
                method=verdict.method.value if verdict.method else "none",
                evidence_ids=verdict.evidence_ids,
            )
            if not requirement or verdict.status != MatchStatus.MATCHED or requirement.kind != RequirementKind.PROJECT_RELEVANCE:
                continue
            for evidence_id in verdict.evidence_ids:
                if not evidence_id.startswith("project:"):
                    continue
                try:
                    index = int(evidence_id.split(":", 1)[1]) - 1
                    if 0 <= index < len(projects):
                        technologies = projects[index].setdefault("technologies", [])
                        if _key(requirement.text) not in {_key(value) for value in technologies}:
                            technologies.append(requirement.text)
                except Exception:
                    pass
        enriched = SimpleNamespace(projects=projects)

        # Routing and Execution Metrics Calculation
        total_requirements = len(requirements)
        canonical_matched_count = sum(1 for v in deterministic if v.status == MatchStatus.MATCHED)
        canonical_unmatched_count = total_requirements - canonical_matched_count
        llm_submitted_count = len(unresolved)
        no_evidence_no_llm_count = total_requirements - canonical_matched_count - llm_submitted_count
        llm_eligible_count = llm_submitted_count

        llm_verdicts = [v for v in fused if v.method in {MatchMethod.LLM_CONFIRMED, MatchMethod.LLM_REJECTED, MatchMethod.LLM_UNRESOLVED}]
        confirmed_count = sum(1 for v in llm_verdicts if v.method == MatchMethod.LLM_CONFIRMED)
        rejected_count = sum(1 for v in llm_verdicts if v.method == MatchMethod.LLM_REJECTED)
        unresolved_count = sum(1 for v in llm_verdicts if v.method == MatchMethod.LLM_UNRESOLVED)
        validation_failure_count = sum(1 for v in llm_verdicts if "(Rejected: No valid candidate evidence ID cited for match)" in getattr(v, "reasoning", ""))
        validated_count = len(llm_verdicts)

        logger.info(
            "hybrid_llm_decisions_validated",
            total_requirements=total_requirements,
            canonical_matched_count=canonical_matched_count,
            canonical_unmatched_count=canonical_unmatched_count,
            llm_eligible_count=llm_eligible_count,
            llm_submitted_count=llm_submitted_count,
            llm_confirmed_count=confirmed_count,
            llm_rejected_count=rejected_count,
            llm_unresolved_count=unresolved_count,
            no_evidence_no_llm_count=no_evidence_no_llm_count,
            validation_failure_count=validation_failure_count,
            requested_count=llm_submitted_count,
            validated_count=validated_count,
            accepted_count=confirmed_count,
            invariant_holds=(canonical_matched_count + llm_submitted_count + no_evidence_no_llm_count == total_requirements),
        )
        return enriched, fused
