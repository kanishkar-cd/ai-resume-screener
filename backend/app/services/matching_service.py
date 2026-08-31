from __future__ import annotations

import asyncio
import hashlib
import json
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
    Evidence, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict,
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
    def build(job: Any, config: Any) -> list[Requirement]:
        rows: list[tuple[RequirementKind, str, bool, bool]] = []
        mandatory = {_key(value) for value in (getattr(config, "mandatory_skills", None) or [])}
        preferred_skills = list(getattr(job, "preferred_skills", None) or [])
        preferred = {_key(value) for value in preferred_skills}
        required_skills = list(getattr(job, "required_skills", None) or [])

        # 1. Required skills (filtering section headers & meta notes)
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

        # 4. Certification, Language, Project requirements (Degree matching disabled)
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
    @staticmethod
    def _projects(extracted: Any) -> list[dict[str, Any]]:
        raw_projs = list(getattr(extracted, "projects", None) or [])
        if raw_projs:
            return raw_projs
        meta = getattr(extracted, "raw_metadata", None) or {}
        if isinstance(meta, dict):
            profile_projs = list((meta.get("affinda_normalized_profile") or {}).get("projects") or [])
            if profile_projs:
                return profile_projs
        return []
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
        # Education evidence disabled (0% weight)
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
                if item.kind not in {"experience", "project"}:
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

            exp_and_proj_evidence = [e for e in evidence if e.kind in {"experience", "project"}]
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
                ("clean code", {"clean code", "readable code", "maintainable code", "clean coding", "code quality", "code standards"}),
                ("mentoring", {"mentor", "mentored", "mentoring", "guidance", "coach", "coaching", "mentorship"}),
                ("junior developers", {"junior developers", "junior engineers", "juniors"}),
                ("team members", {"team members", "cross-functional team members", "cross-functional teams", "team", "developers", "peers"}),
                ("user interfaces", {"user interfaces", "user interface", "ui", "interfaces", "components"}),
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
            certs = [(c.get("name") or c.get("title") or "") if isinstance(c, dict) else str(c).strip() for c in (getattr(resume, "certifications", None) or [])]
            certs = [c for c in certs if c]
            evidence_terms = [term for e in evidence for term in e.canonical_terms if term]
            evidence_text = " ".join(e.text for e in evidence).casefold()
            candidate_pool = list(dict.fromkeys([*candidates, *certs, *evidence_terms]))

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
            return MatchVerdict(
                requirement_id=requirement.requirement_id, status=MatchStatus.NO_MATCH,
                confidence=1, reasoning="Education matching disabled.",
            )

        elif requirement.kind in {RequirementKind.EXPERIENCE, RequirementKind.CONTEXTUAL_EXPERIENCE}:
            req_text = requirement.canonical_value or requirement.text
            exp_items = getattr(resume, "experience", None) or []
            total_months = sum(item.get("duration_months") or 0 for item in exp_items)
            
            m_range = re.search(r"(\d+)\s*[-–to]+\s*(\d+)\s+years?", req_text, re.I)
            m_min = re.search(r"(?:minimum|at\s+least|min)\s+(\d+)\s+years?", req_text, re.I) or re.search(r"(\d+)\+\s*years?", req_text, re.I) or re.search(r"(\d+)\s+years?", req_text, re.I)
            if m_range:
                job_min = int(m_range.group(1)) * 12
            elif m_min:
                job_min = int(m_min.group(1)) * 12
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


class EvidencePrefilter:
    def __init__(self, threshold: float, limit: int) -> None:
        self.threshold, self.limit = threshold, limit

    def select(self, requirement: Requirement, evidence: list[Evidence]) -> list[Evidence]:
        if not evidence:
            return []

        # Filter candidate evidence by requirement kind priority
        if requirement.kind == RequirementKind.RESPONSIBILITY:
            kind_evidence = [e for e in evidence if e.kind in {"experience", "project", "summary"}]
            if not kind_evidence:
                return []
            target_evidence = kind_evidence
        elif requirement.kind == RequirementKind.PROJECT_RELEVANCE:
            kind_evidence = [e for e in evidence if e.kind in {"project", "experience", "summary"}]
            if not kind_evidence:
                return []
            target_evidence = kind_evidence
        elif requirement.kind == RequirementKind.DEGREE:
            kind_evidence = [e for e in evidence if e.kind == "education"]
            target_evidence = kind_evidence if kind_evidence else evidence
        elif requirement.kind == RequirementKind.CERTIFICATION:
            kind_evidence = [e for e in evidence if e.kind == "certification"]
            target_evidence = kind_evidence if kind_evidence else evidence
        else:
            target_evidence = evidence

        req_lower = requirement.text.casefold()
        synonym_phrases: set[str] = set()
        for term, syns in SEMANTIC_SYNONYMS.items():
            if term in req_lower or any(t in req_lower for t in term.split()):
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

        if scored:
            scored.sort(key=lambda row: (-row[0], row[1]))
            passing = [row[2] for row in scored if row[0] >= self.threshold]
            return passing[: self.limit] if passing else [row[2] for row in scored[: self.limit]]

        # Fallback profile evidence when no specific token overlap exists (for responsibilities, degrees, certifications)
        if requirement.kind in {RequirementKind.SKILL, RequirementKind.REQUIRED_SKILL, RequirementKind.PREFERRED_SKILL}:
            return []

        allowed_kinds = {"experience", "project", "summary"} if requirement.kind == RequirementKind.RESPONSIBILITY else {"skills", "project", "experience", "summary", "certification"}
        fallback_evidence = [e for e in target_evidence if e.kind in allowed_kinds]
        return (fallback_evidence if fallback_evidence else target_evidence)[: self.limit]


class GroqTokenBudgetGate:
    _instance: GroqTokenBudgetGate | None = None
    _lock: asyncio.Lock | None = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.window_seconds = 60.0
        self.usage_history: list[tuple[float, int]] = []
        self.reserved_in_flight = 0

        self.header_remaining_tokens: int | None = None
        self.header_reset_timestamp: float | None = None
        self.header_remaining_requests: int | None = None

    @classmethod
    def get_gate(cls, settings: Settings | None = None) -> GroqTokenBudgetGate:
        if cls._instance is None:
            cls._instance = cls(settings)
        if cls._instance._lock is None:
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    @classmethod
    def reset_gate(cls) -> None:
        """Reset gate state for testing isolation."""
        if cls._instance is not None:
            cls._instance.usage_history.clear()
            cls._instance.reserved_in_flight = 0
            cls._instance.header_remaining_tokens = None
            cls._instance.header_reset_timestamp = None
            cls._instance.header_remaining_requests = None

    @property
    def tpm_limit(self) -> int:
        return getattr(self.settings, "GROQ_TPM_LIMIT", 8000)

    @property
    def safety_margin(self) -> float:
        return getattr(self.settings, "GROQ_TPM_SAFETY_MARGIN", 0.10)

    @property
    def usable_tpm(self) -> int:
        return int(self.tpm_limit * (1.0 - self.safety_margin))

    def estimate_tokens(self, payload: dict[str, Any], output_estimate: int | None = None) -> int:
        """Estimate total tokens required (prompt input + estimated output)."""
        prompt_text = ""
        user_content = ""
        for msg in payload.get("messages", []):
            content = str(msg.get("content", ""))
            prompt_text += content
            if msg.get("role") == "user":
                user_content = content

        input_tokens = int(len(prompt_text) / 2.8 * 1.05) + 10
        if output_estimate is None:
            try:
                data = json.loads(user_content)
                req_count = len(data.get("requirements", []))
                output_estimate = min(350, max(120, req_count * 20))
            except Exception:
                output_estimate = getattr(self.settings, "GROQ_ESTIMATED_OUTPUT_TOKENS", 350)
        return input_tokens + output_estimate

    async def acquire_reservation(self, estimated_tokens: int, correlation_id: str = "") -> None:
        """
        Check token budget. If insufficient capacity, wait until reset/capacity available.
        Once capacity exists, reserve estimated_tokens and return.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()

        while True:
            async with self._lock:
                now = time.monotonic()

                self.usage_history = [(ts, tok) for ts, tok in self.usage_history if now - ts < self.window_seconds]
                local_window_used = sum(tok for _, tok in self.usage_history)

                if self.header_reset_timestamp is not None:
                    if now >= self.header_reset_timestamp or self.reserved_in_flight == 0:
                        self.header_remaining_tokens = None
                        self.header_reset_timestamp = None

                if self.header_remaining_tokens is not None:
                    avail_from_header = max(0, self.header_remaining_tokens - self.reserved_in_flight)
                    avail_from_local = max(0, self.usable_tpm - local_window_used - self.reserved_in_flight)
                    available_tokens = min(avail_from_header, avail_from_local)
                else:
                    available_tokens = max(0, self.usable_tpm - local_window_used - self.reserved_in_flight)

                if available_tokens >= estimated_tokens:
                    self.reserved_in_flight += estimated_tokens
                    self._last_wait_ts = None
                    logger.info(
                        "llm_request_allowed",
                        reserved_tokens=estimated_tokens,
                        available_tokens_before=available_tokens,
                        usable_limit=self.usable_tpm,
                        correlation_id=correlation_id,
                    )
                    return

                wait_seconds = 1.0
                if self.header_reset_timestamp is not None and self.header_reset_timestamp > now:
                    wait_seconds = max(0.05, self.header_reset_timestamp - now + 0.05)
                elif self.usage_history:
                    needed_release = estimated_tokens - available_tokens
                    accumulated = 0
                    target_ts = self.usage_history[0][0]
                    for ts, tok in self.usage_history:
                        accumulated += tok
                        if accumulated >= needed_release:
                            target_ts = ts
                            break
                    wait_seconds = max(0.05, (target_ts + self.window_seconds) - now + 0.05)

                wait_seconds = min(wait_seconds, 60.0)
                self._last_wait_ts = now

                logger.info(
                    "llm_token_budget_wait",
                    required_tokens=estimated_tokens,
                    available_tokens=available_tokens,
                    wait_seconds=round(wait_seconds, 2),
                    usable_limit=self.usable_tpm,
                    correlation_id=correlation_id,
                )

            await asyncio.sleep(wait_seconds)

    async def release_reservation(self, estimated_tokens: int) -> None:
        """Release in-flight reservation."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)

    async def record_response(self, estimated_tokens: int, response: httpx.Response | None = None, actual_tokens: int | None = None) -> None:
        """Release reservation, record used tokens into sliding window, sync headers."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)
            now = time.monotonic()

            used_tokens = actual_tokens if actual_tokens is not None else estimated_tokens
            self.usage_history.append((now, used_tokens))

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

    async def record_429(self, estimated_tokens: int, response: httpx.Response | None = None) -> float:
        """Handle 429 response: release reservation, update reset timestamp, return wait seconds."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self.reserved_in_flight = max(0, self.reserved_in_flight - estimated_tokens)
            now = time.monotonic()

            self.header_remaining_tokens = 0
            retry_after = 2.0

            if response is not None and hasattr(response, "headers"):
                headers = response.headers
                if isinstance(headers, dict) or hasattr(headers, "get"):
                    hdr_retry = headers.get("retry-after") or headers.get("Retry-After")
                    res_tok = headers.get("x-ratelimit-reset-tokens")
                    if hdr_retry is not None and type(hdr_retry) in (int, float, str):
                        try:
                            retry_after = float(hdr_retry)
                        except (ValueError, TypeError):
                            pass
                    elif res_tok is not None and type(res_tok) in (int, float, str):
                        try:
                            res_str = str(res_tok).strip()
                            if res_str.endswith("ms"):
                                retry_after = float(res_str[:-2]) / 1000.0
                            elif res_str.endswith("s"):
                                retry_after = float(res_str[:-1])
                            else:
                                retry_after = float(res_str)
                        except (ValueError, TypeError):
                            pass

            self.header_reset_timestamp = now + retry_after
            return retry_after


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
        if not self.enabled or not requirements:
            return []

        # Safe batch chunking to avoid LLM token overflow on large inputs (> 15 requirements)
        if len(requirements) > 15:
            all_verdicts: list[MatchVerdict] = []
            chunk_size = 12
            for i in range(0, len(requirements), chunk_size):
                req_chunk = requirements[i:i + chunk_size]
                chunk_allowed = {
                    r.requirement_id: allowed_evidence.get(r.requirement_id, set())
                    for r in req_chunk
                } if allowed_evidence else None
                chunk_ev_ids = {eid for r in req_chunk for eid in (chunk_allowed.get(r.requirement_id, set()) if chunk_allowed else set())}
                chunk_ev = [e for e in evidence if e.evidence_id in chunk_ev_ids] if chunk_ev_ids else evidence
                chunk_verdicts = await self.evaluate(req_chunk, chunk_ev, chunk_allowed)
                all_verdicts.extend(chunk_verdicts)
            return all_verdicts
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
        gate = GroqTokenBudgetGate.get_gate(self.settings)
        estimated_tokens = gate.estimate_tokens(payload)

        parsed: LLMVerdictBatch | None = None
        client = self._get_client(self.settings.GROQ_TIMEOUT_SECONDS)
        max_retries = max(1, getattr(self.settings, "GROQ_MAX_RETRIES", 2))
        total_attempts = max_retries + 1

        for attempt in range(total_attempts):
            await gate.acquire_reservation(estimated_tokens, correlation_id=digest[:8])
            try:
                response = await client.post(
                    f"{self.settings.GROQ_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.GROQ_API_KEY}"},
                    json=payload,
                    timeout=self.settings.GROQ_TIMEOUT_SECONDS,
                )
                response.raise_for_status()

                resp_json = response.json()
                usage = resp_json.get("usage", {})
                actual_tokens = usage.get("total_tokens")

                await gate.record_response(estimated_tokens, response=response, actual_tokens=actual_tokens)

                logger.info(
                    "llm_request_completed",
                    attempt=attempt + 1,
                    status_code=response.status_code,
                    estimated_tokens=estimated_tokens,
                    actual_tokens=actual_tokens,
                    correlation_id=digest[:8],
                )

                content = resp_json["choices"][0]["message"]["content"]
                parsed = LLMVerdictBatch.model_validate(json.loads(content) if isinstance(content, str) else content)
                break
            except Exception as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                resp_obj = getattr(exc, "response", None)

                if status_code == 429:
                    retry_after = await gate.record_429(estimated_tokens, response=resp_obj)
                    logger.info(
                        "llm_429_received",
                        attempt=attempt + 1,
                        status_code=429,
                        retry_after=retry_after,
                        correlation_id=digest[:8],
                    )
                else:
                    await gate.release_reservation(estimated_tokens)

                resp_body = None
                if resp_obj is not None:
                    try:
                        resp_body = resp_obj.text
                    except Exception:
                        pass
                is_last_attempt = (attempt == total_attempts - 1)

                if status_code in {400, 401, 403, 404}:
                    logger.error(
                        "hybrid_match_llm_client_error",
                        attempt=attempt + 1,
                        status_code=status_code,
                        error_type=type(exc).__name__,
                        response_body=resp_body,
                    )
                    break

                if is_last_attempt:
                    logger.error(
                        "hybrid_match_llm_all_retries_failed",
                        attempt=attempt + 1,
                        status_code=status_code,
                        error_type=type(exc).__name__,
                        response_body=resp_body,
                    )
                    break

                retry_after_hdr = None
                if status_code == 429 and resp_obj is not None:
                    retry_after_hdr = resp_obj.headers.get("retry-after") or resp_obj.headers.get("Retry-After")

                used_retry_after = False
                delay = 2.0 * (2 ** attempt)
                if retry_after_hdr:
                    try:
                        parsed_delay = float(retry_after_hdr)
                        if parsed_delay >= 0:
                            delay = parsed_delay
                            used_retry_after = True
                    except (ValueError, TypeError):
                        pass

                delay = min(delay, 15.0)

                logger.warning(
                    "hybrid_match_llm_attempt_failed",
                    attempt=attempt + 1,
                    status_code=status_code,
                    error_type=type(exc).__name__,
                    delay_seconds=round(delay, 2),
                    used_retry_after=used_retry_after,
                    response_body=resp_body,
                )
                await asyncio.sleep(delay)

        if parsed is None:
            return []
        validated = self._validate(parsed, requirements, evidence, allowed_evidence)
        self._cache[digest] = validated
        self._cache.move_to_end(digest)
        while len(self._cache) > self.settings.HYBRID_MATCHING_CACHE_SIZE:
            self._cache.popitem(last=False)
        return [verdict.model_copy(deep=True) for verdict in validated]

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
        all_evidence_ids = {item.evidence_id for item in evidence}
        threshold = self.settings.HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD
        result: list[MatchVerdict] = []
        seen: set[str] = set()

        for item in batch.verdicts:
            req_id = item.requirement_id
            if req_id not in requirement_ids or req_id in seen:
                continue
            seen.add(req_id)

            # Determine valid supplied evidence IDs for this specific requirement
            if allowed_evidence and req_id in allowed_evidence:
                req_supplied_ids = allowed_evidence[req_id] & all_evidence_ids
            else:
                req_supplied_ids = all_evidence_ids

            # Normalize and validate all cited evidence IDs
            raw_cited_ids = list(item.evidence_ids) if item.evidence_ids else []
            valid_cited_ids: list[str] = []
            for raw_id in raw_cited_ids:
                norm_id = self._normalize_evidence_id(raw_id, req_supplied_ids)
                if norm_id and norm_id not in valid_cited_ids:
                    valid_cited_ids.append(norm_id)

            # If no valid citations found from raw list, but only 1 evidence item was supplied for this requirement:
            if not valid_cited_ids and not raw_cited_ids and len(req_supplied_ids) == 1:
                valid_cited_ids = list(req_supplied_ids)

            has_valid_evidence = bool(valid_cited_ids)

            raw_status_str = str(getattr(item.status, "value", item.status)).upper()
            is_matched_raw = raw_status_str in {"MATCHED", "MATCH"}
            is_partial_raw = raw_status_str in {"PARTIALLY_MATCHED", "PARTIAL"}
            is_no_match_raw = raw_status_str in {"NO_MATCH", "UNMATCHED", "REJECTED"}

            confirmed = (is_matched_raw or is_partial_raw) and item.confidence >= threshold and has_valid_evidence

            if confirmed:
                if is_partial_raw:
                    status = MatchStatus.PARTIALLY_MATCHED
                else:
                    status = MatchStatus.MATCHED
                method = MatchMethod.LLM_CONFIRMED
                reasoning = item.reasoning or "LLM confirmed requirement match from candidate evidence."
            elif is_no_match_raw:
                status = MatchStatus.NO_MATCH
                method = MatchMethod.LLM_REJECTED
                reasoning = item.reasoning or "LLM verified requirement is unmet."
            else:
                status = MatchStatus.UNRESOLVED
                method = MatchMethod.LLM_UNRESOLVED
                if (is_matched_raw or is_partial_raw) and not has_valid_evidence:
                    reasoning = (item.reasoning or "") + " (Rejected: No valid candidate evidence ID cited for match)."
                else:
                    reasoning = item.reasoning or "LLM verdict unresolved by evidence validation."

            coverage_val = float(getattr(item, "coverage", 1.0 if confirmed and not is_partial_raw else (0.5 if is_partial_raw else 0.0)) or (1.0 if confirmed and not is_partial_raw else 0.0))
            if confirmed and not is_partial_raw and coverage_val < 0.45:
                coverage_val = max(coverage_val, 0.50)

            result.append(MatchVerdict(
                requirement_id=req_id,
                status=status,
                confidence=item.confidence if (confirmed or is_no_match_raw) else (item.confidence if raw_status_str == "UNRESOLVED" else 0.0),
                evidence_ids=sorted(valid_cited_ids) if confirmed else [],
                reasoning=reasoning.strip(),
                method=method,
                coverage=coverage_val,
                matched_concepts=getattr(item, "matched_concepts", []) or [],
                missing_concepts=getattr(item, "missing_concepts", []) or [],
            ))
        return result

    def _payload(self, requirements: list[Requirement], evidence: list[Evidence]) -> dict[str, Any]:
        req_list = [
            {
                "requirement_id": r.requirement_id,
                "kind": r.kind.value,
                "text": r.text,
                "required": r.required,
            }
            for r in requirements
        ]
        ev_list = [
            {
                "evidence_id": e.evidence_id,
                "kind": e.kind,
                "text": e.text,
                "canonical_terms": e.canonical_terms,
            }
            for e in evidence
        ]
        content = json.dumps({"requirements": req_list, "evidence": ev_list})
        system_prompt = (
            "You are an enterprise AI Resume Matching Evaluator. Evaluate whether supplied candidate evidence satisfies JD requirements.\n\n"
            "STATUS DEFINITIONS:\n"
            "- MATCHED: Direct or equivalent proof satisfying requirement.\n"
            "- PARTIALLY_MATCHED: Satisfies part of compound/complex requirement, but key part unsupported.\n"
            "- NO_MATCH: No relevant proof.\n"
            "- UNRESOLVED: Ambiguous or insufficient evidence.\n\n"
            "EVALUATION RULES & HIERARCHY:\n"
            "1. TIER 1 (Direct): Explicit mention of required skill/responsibility -> MATCHED.\n"
            "2. TIER 2 (Semantic Equivalents): Technical equivalence, industry aliases, or standardized concepts (JWT/RBAC->auth, async/await->asynchronous, CI/CD pipelines, MongoDB/PostgreSQL->schema design, REST endpoints->REST APIs, root cause->debugging) -> MATCHED.\n"
            "3. TIER 3 (Implementation): Practical proof in projects, experience, or internships is valid.\n"
            "4. TIER 4 (Strict Negative Boundaries): General language (JS) NEVER satisfies framework (Next.js). React NEVER satisfies Next.js without proof. Backend NEVER satisfies Docker/AWS without proof. Do not invent evidence.\n"
            "5. Rule 5 (Compound): Decompose compound expectations. If major portion shown but key concept missing -> PARTIALLY_MATCHED.\n"
            "6. Rule 6 (Citations): Every MATCHED or PARTIALLY_MATCHED verdict MUST cite valid evidence_ids.\n\n"
            "DOMAINS: Software Engineering, QA / Testing, SecOps / SOC, Data Engineering, DevOps / SRE, Compound Responsibilities.\n\n"
            "OUTPUT FORMAT:\n"
            "Return JSON: {\"verdicts\":[{\"requirement_id\":\"string\",\"status\":\"MATCHED|PARTIALLY_MATCHED|NO_MATCH|UNRESOLVED\",\"confidence\":0.0-1.0,\"evidence_ids\":[\"string\"],\"reasoning\":\"1 concise sentence under 15 words.\"}]}"
        )
        return {
            "model": self.settings.GROQ_MODEL,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
        }


class HybridMatchingService:
    def __init__(self, settings: Settings | None = None, evaluator: GroqMatchEvaluator | None = None) -> None:
        self.settings = settings or get_settings()
        self.evaluator = evaluator or GroqMatchEvaluator(self.settings)
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

        llm = await self.evaluator.evaluate(unresolved, list(supplied.values()), allowed_evidence) if unresolved else []
        llm_by_id = {item.requirement_id: item for item in llm}
        fused = [llm_by_id.get(item.requirement_id, item) for item in deterministic]
        projects = EvidenceBuilder._projects(extracted)
        for project in projects:
            project["technologies"] = list(project.get("technologies") or [])
        requirement_by_id = {item.requirement_id: item for item in requirements}
        for verdict in fused:
            requirement = requirement_by_id.get(verdict.requirement_id)
            if requirement:
                verdict.requirement_text = requirement.text
                verdict.kind = requirement.kind
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
