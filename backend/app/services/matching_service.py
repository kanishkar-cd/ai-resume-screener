from __future__ import annotations

import asyncio
import hashlib
import json
import re
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
    RequirementKind.DEGREE,
    RequirementKind.CERTIFICATION,
    RequirementKind.LANGUAGE,
    RequirementKind.PROJECT_RELEVANCE,
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

    @staticmethod
    def build(job: Any, config: Any) -> list[Requirement]:
        rows: list[tuple[RequirementKind, str, bool, bool]] = []
        mandatory = {_key(value) for value in (getattr(config, "mandatory_skills", None) or [])}
        preferred_skills = list(getattr(job, "preferred_skills", None) or [])
        preferred = {_key(value) for value in preferred_skills}
        required_skills = list(getattr(job, "required_skills", None) or [])

        # 1. Add required skills (or skills not marked as preferred)
        if required_skills:
            for value in required_skills:
                key = _key(value)
                rows.append((RequirementKind.SKILL, value, True, key in mandatory))
        else:
            for value in getattr(job, "skills", None) or []:
                key = _key(value)
                if key not in preferred:
                    rows.append((RequirementKind.SKILL, value, True, key in mandatory))

        # 2. Explicitly add preferred skills with required=False
        for value in preferred_skills:
            rows.append((RequirementKind.SKILL, value, False, False))

        # 3. Add any remaining skills from job.skills
        for value in getattr(job, "skills", None) or []:
            key = _key(value)
            if key in preferred:
                rows.append((RequirementKind.SKILL, value, False, False))
            else:
                rows.append((RequirementKind.SKILL, value, True, key in mandatory))

        for value in getattr(job, "degree_requirements", None) or []:
            rows.append((RequirementKind.DEGREE, value, True, False))
        for value in [
            *(getattr(job, "certifications", None) or []),
            *(getattr(config, "required_certifications", None) or []),
        ]:
            rows.append((RequirementKind.CERTIFICATION, value, True, False))
        for value in getattr(config, "required_languages", None) or []:
            rows.append((RequirementKind.LANGUAGE, value, True, False))
        for value in getattr(job, "project_requirements", None) or []:
            rows.append((RequirementKind.PROJECT_RELEVANCE, value, True, False))
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
    @staticmethod
    def _projects(extracted: Any) -> list[dict[str, Any]]:
        projects = [dict(item) for item in (getattr(extracted, "projects", None) or [])]
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
    def build(extracted: Any) -> list[Evidence]:
        result: list[Evidence] = []
        for index, project in enumerate(EvidenceBuilder._projects(extracted), start=1):
            name = project.get("name") or ""
            description = project.get("description") or ""
            technologies = project.get("technologies") or []
            text = " ".join(value for value in [name, description, *technologies] if value).strip()
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
        for index, item in enumerate(getattr(extracted, "education", None) or [], start=1):
            degree = item.get("degree") or ""
            field = item.get("field_of_study") or ""
            inst = item.get("institution") or ""
            text = " ".join(v for v in [degree, field, inst] if v).strip()
            if text:
                result.append(Evidence(
                    evidence_id=f"education:{index}", kind="education", text=text,
                    canonical_terms=[v for v in [degree, field] if v],
                ))
        certs = [c.strip() for c in (getattr(extracted, "certifications", None) or []) if str(c).strip()]
        for index, cert in enumerate(certs, start=1):
            result.append(Evidence(
                evidence_id=f"certification:{index}", kind="certification", text=cert,
                canonical_terms=[cert],
            ))
        langs = [l.strip() for l in (getattr(extracted, "languages", None) or []) if str(l).strip()]
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
                "redis": {"redis"},
                "docker": {"docker"},
                "kubernetes": {"kubernetes", "k8s"},
                "python": {"python"},
                "aws": {"aws", "amazon web services"},
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
            for tech_key, aliases in tech_aliases.items():
                if any(re.search(rf"\b{re.escape(a)}\b", req_lower) for a in aliases):
                    semantic_concepts.append((tech_key, "tech", aliases))

            # 2. Identify Actions
            for action_key, syns in action_synonyms.items():
                if re.search(rf"\b{re.escape(action_key)}\b", req_lower):
                    stemmed_syns = {_stem_token(s) for s in syns}
                    semantic_concepts.append((action_key, "action", stemmed_syns))

            # 3. Identify Domain Activities / Deliverables if not fully covered
            domain_patterns = {
                "backend apis": {"backend apis", "backend api", "apis", "api", "rest apis", "rest api"},
                "apis": {"backend apis", "backend api", "apis", "api", "rest apis", "rest api"},
                "rest apis": {"rest api", "rest apis", "restful api", "restful apis"},
                "user interfaces": {"user interfaces", "user interface", "ui", "interfaces", "components"},
                "database schemas": {"database schemas", "database schema", "schemas", "schema", "data models"},
                "schemas": {"database schemas", "database schema", "schemas", "schema"},
                "database": {"database", "databases", "relational database", "relational databases", "schemas", "schema", "data models"},
                "authentication": {"authentication", "auth", "jwt", "authorization"},
                "microservices": {"microservices", "microservice", "services"},
                "ci/cd pipelines": {"ci/cd", "pipelines", "pipeline", "automation"},
                "unit tests": {"unit tests", "testing", "tests", "integration tests"},
                "siem": {"siem", "splunk", "qradar"},
                "security alerts": {"security alerts", "alerts"},
                "security events": {"security events", "logs", "events"},
                "incidents": {"production incidents", "incident", "incidents", "security events", "events"},
                "root causes": {"root causes", "root cause", "incident findings", "findings", "recommendations"},
                "incident triage": {"incident triage", "triage", "investigation"},
                "incident findings": {"incident findings", "findings", "investigation findings", "escalation recommendations", "recommendations", "reports"},
                "findings": {"findings", "recommendation", "recommendations", "reports"},
                "vulnerability assessment": {"vulnerability assessment", "vulnerabilities", "vulnerability"},
                "cloud infrastructure": {"cloud infrastructure", "infrastructure", "deployments", "cloud"},
            }
            for domain_key, aliases in domain_patterns.items():
                if domain_key not in {c[0] for c in semantic_concepts}:
                    if any(re.search(rf"\b{re.escape(a)}\b", req_lower) for a in aliases):
                        semantic_concepts.append((domain_key, "domain", aliases))

            # If semantic_concepts only contains generic actions and req_text has multiple comma-separated items (e.g. "Support item1, item2, ..., item20"):
            has_tech_or_domain = any(c[1] in {"tech", "domain"} for c in semantic_concepts)
            raw_clauses = [c.strip() for c in re.split(r"[,;]|\s+(?:and|&|\/|\+)\s+", req_text, flags=re.I) if c.strip()]
            if not has_tech_or_domain and len(raw_clauses) >= 3:
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
                        if any(re.search(rf"\b{re.escape(a)}\b", e_text_lower) for a in targets) or any(a in e_terms for a in targets):
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

            total_concepts_count = len(matched_concepts) + len(missing_concepts)
            coverage = round(len(matched_concepts) / total_concepts_count, 2) if total_concepts_count > 0 else 0.0

            # 45% Business Rule Classification:
            # Coverage >= 45% -> MATCHED
            # Coverage > 0% and < 45% -> PARTIALLY_MATCHED
            # Coverage == 0% -> UNRESOLVED (routes to LLM fallback) / UNMATCHED
            if coverage >= 0.45:
                status = MatchStatus.MATCHED
                method = MatchMethod.ALIAS if ev_ids else MatchMethod.EXACT
                reasoning = f"Contextual evidence satisfies {int(coverage * 100)}% of responsibility concepts (>=45% shortlisting threshold)."
            elif coverage > 0.0:
                status = MatchStatus.PARTIALLY_MATCHED
                method = MatchMethod.ALIAS if ev_ids else MatchMethod.EXACT
                reasoning = f"Contextual evidence partially satisfies {int(coverage * 100)}% of responsibility concepts (<45% threshold)."
            else:
                status = MatchStatus.UNRESOLVED
                method = None
                reasoning = "No direct deterministic concept match; requires semantic experiential review."

            return MatchVerdict(
                requirement_id=requirement.requirement_id,
                status=status,
                confidence=1.0 if coverage >= 0.45 else (coverage if coverage > 0 else 0.0),
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

        if requirement.kind == RequirementKind.SKILL:
            aliases = SKILL_ALIASES
            candidates = list(getattr(resume, "skills", None) or [])
            certs = list(getattr(resume, "certifications", None) or [])
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
                            if clean_part in {"database concepts", "database", "debugging", "concepts", "fundamentals", "basics", "principles", "json", "problem-solving ability", "teamwork", "soft skills"} and matched_skills_list:
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
            aliases = DEGREE_ALIASES
            edu_items = getattr(resume, "education", None) or []
            candidates = [item.get("degree") for item in edu_items if item.get("degree")]
            fields = [item.get("field_of_study") for item in edu_items if item.get("field_of_study")]
            edu_text = " ".join(e.text for e in evidence if e.kind == "education").casefold()

            required_rank = ComponentScoringService.degree_rank(req_text)
            if required_rank and any(ComponentScoringService.degree_rank(value) >= required_rank for value in candidates):
                return MatchVerdict(
                    requirement_id=requirement.requirement_id, status=MatchStatus.MATCHED,
                    confidence=1, reasoning="Degree taxonomy level satisfies requirement.",
                    method=MatchMethod.TAXONOMY,
                )

            # Check discipline alternatives (e.g. "Computer Science, Engineering, Information Technology")
            disc_alts = re.split(r"[,;/]|\s+or\s+|\s+and\s+", req_text, flags=re.IGNORECASE)
            for d in [a.strip().casefold() for a in disc_alts if a.strip()]:
                if any(d in (f or "").casefold() for f in fields) or any(d in (c or "").casefold() for c in candidates) or (len(d) >= 4 and d in edu_text):
                    return MatchVerdict(
                        requirement_id=requirement.requirement_id, status=MatchStatus.MATCHED,
                        confidence=1, reasoning=f"Educational background satisfies requirement ({d.title()}).",
                        method=MatchMethod.TAXONOMY,
                    )

            return MatchVerdict(
                requirement_id=requirement.requirement_id, status=MatchStatus.NO_MATCH,
                confidence=1, reasoning="No deterministic canonical match.",
            )

        elif requirement.kind == RequirementKind.CERTIFICATION:
            aliases = CERTIFICATION_ALIASES
            candidates = list(getattr(resume, "certifications", None) or [])
        elif requirement.kind == RequirementKind.LANGUAGE:
            aliases = LANGUAGE_ALIASES
            candidates = list(getattr(resume, "languages", None) or [])
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


class EvidencePrefilter:
    def __init__(self, threshold: float, limit: int) -> None:
        self.threshold, self.limit = threshold, limit

    def select(self, requirement: Requirement, evidence: list[Evidence]) -> list[Evidence]:
        if not evidence:
            return []

        # Filter candidate evidence by requirement kind priority
        if requirement.kind == RequirementKind.RESPONSIBILITY:
            kind_evidence = [e for e in evidence if e.kind in {"experience", "project"}]
            if not kind_evidence:
                return []
            target_evidence = kind_evidence
        elif requirement.kind == RequirementKind.PROJECT_RELEVANCE:
            kind_evidence = [e for e in evidence if e.kind == "project"]
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

        required = _stem_tokens(requirement.text)
        scored = []
        for item in target_evidence:
            overlap = len(required & _stem_tokens(item.text)) / len(required) if required else 0.0
            if overlap > 0:
                scored.append((overlap, item.evidence_id, item))
        if scored:
            scored.sort(key=lambda row: (-row[0], row[1]))
            passing = [row[2] for row in scored if row[0] >= self.threshold]
            selected = passing[: self.limit] if passing else [row[2] for row in scored[: self.limit]]
            selected_ids = {e.evidence_id for e in selected}
            for e in target_evidence:
                allowed_kinds = {"experience", "project"} if requirement.kind == RequirementKind.RESPONSIBILITY else {"skills", "project", "experience"}
                if e.kind in allowed_kinds and e.evidence_id not in selected_ids and len(selected) < self.limit:
                    selected.append(e)
                    selected_ids.add(e.evidence_id)
            return selected

        # Fallback profile evidence when no specific token overlap exists (only for responsibilities and projects)
        if requirement.kind in {RequirementKind.RESPONSIBILITY, RequirementKind.PROJECT_RELEVANCE}:
            allowed_kinds = {"experience", "project"} if requirement.kind == RequirementKind.RESPONSIBILITY else {"project"}
            skills_and_projects = [e for e in target_evidence if e.kind in allowed_kinds]
            return (skills_and_projects if skills_and_projects else target_evidence)[: self.limit]
        return []


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
        client = self._get_client(self.settings.GROQ_TIMEOUT_SECONDS)
        for attempt in range(max(2, self.settings.GROQ_MAX_RETRIES + 1)):
            try:
                response = await client.post(
                    f"{self.settings.GROQ_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.GROQ_API_KEY}"},
                    json=payload,
                    timeout=self.settings.GROQ_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                parsed = LLMVerdictBatch.model_validate(json.loads(content) if isinstance(content, str) else content)
                break
            except Exception as exc:
                logger.warning("hybrid_match_llm_attempt_failed", attempt=attempt + 1, error_type=type(exc).__name__)
                if attempt < max(2, self.settings.GROQ_MAX_RETRIES + 1) - 1:
                    await asyncio.sleep(5.0)
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
            if item.requirement_id not in requirement_ids or item.requirement_id in seen:
                continue
            seen.add(item.requirement_id)
            valid_evidence = bool(item.evidence_ids) and all(
                value in evidence_ids for value in item.evidence_ids
            )
            # MATCHED strictly requires valid evidence citation from supplied candidate evidence
            confirmed = item.status == MatchStatus.MATCHED and item.confidence >= threshold and valid_evidence
            accepted_no_match = item.status == MatchStatus.NO_MATCH
            is_unresolved = item.status == MatchStatus.UNRESOLVED

            if confirmed:
                status = MatchStatus.MATCHED
                method = MatchMethod.LLM_CONFIRMED
                reasoning = item.reasoning or "LLM confirmed requirement match from candidate evidence."
            elif accepted_no_match:
                status = MatchStatus.NO_MATCH
                method = MatchMethod.LLM_REJECTED
                reasoning = item.reasoning or "LLM verified requirement is unmet."
            else:
                status = MatchStatus.UNRESOLVED
                method = MatchMethod.LLM_UNRESOLVED
                if item.status == MatchStatus.MATCHED and not valid_evidence:
                    reasoning = (item.reasoning or "") + " (Rejected: No valid candidate evidence ID cited for match)."
                else:
                    reasoning = item.reasoning or "LLM verdict unresolved by evidence validation."

            coverage_val = float(getattr(item, "coverage", 1.0 if confirmed else (0.0 if accepted_no_match else 0.0)) or (1.0 if confirmed else 0.0))
            if confirmed and coverage_val < 0.45:
                coverage_val = max(coverage_val, 0.50)

            result.append(MatchVerdict(
                requirement_id=item.requirement_id,
                status=status,
                confidence=item.confidence if (confirmed or accepted_no_match) else (item.confidence if is_unresolved else 0.0),
                evidence_ids=item.evidence_ids if valid_evidence else [],
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
            "You are an enterprise AI Resume Matching Evaluator. Your job is to strictly evaluate whether supplied Job Description (JD) requirements are satisfied by the supplied candidate resume evidence.\n\n"
            "EVALUATION STATUS DEFINITIONS:\n"
            "- MATCHED: The candidate evidence contains direct or legitimately equivalent proof satisfying the requirement.\n"
            "- NO_MATCH: The candidate evidence does not contain sufficient or relevant proof to support the requirement.\n"
            "- UNRESOLVED: The candidate evidence contains related, partial, or ambiguous context, but cannot conclusively establish the requirement.\n\n"
            "REQUIREMENT TYPE RULES:\n"
            "1. SKILL requirements: Evaluate if the candidate explicitly possesses the tool/skill in skills list, project technologies, or work experience. "
            "Semantic equivalence is accepted (e.g., 'CSS' for 'CSS3 fundamentals', 'Git/GitHub' for 'Git'). "
            "Never infer distinct or unrelated technologies (e.g., MongoDB != MySQL, JavaScript != TypeScript, Vercel != AWS, Node.js != Docker).\n"
            "2. RESPONSIBILITY requirements: Must be supported by experiential evidence in work experience, internships, or hands-on technical projects/labs demonstrating the candidate actively performed the task. "
            "For fresher/entry-level candidates, practical project implementations, lab setups (e.g., SOC lab, ETL data pipeline, automated QA suite, backend API service), and coursework projects serve as valid experiential evidence when the candidate explicitly performed the activity. "
            "Evaluate action, object, and execution context semantically rather than requiring verbatim sentence matching across domains:\n"
            "   - Software Engineering: 'Built REST APIs using Node.js and Express.js' satisfies 'Build and maintain backend APIs'.\n"
            "   - QA / Testing: 'Created Playwright end-to-end test suite and triaged failed tests' satisfies 'Execute automated testing and debug defects'.\n"
            "   - SecOps / SOC: 'Configured Wazuh lab to collect and review security events' satisfies 'Monitor SIEM security alerts'.\n"
            "   - Data Engineering: 'Developed an ETL pipeline using Python and SQL' satisfies 'Build data pipelines'.\n"
            "   - DevOps / SRE: 'Configured CI/CD workflow and monitored container metrics' satisfies 'Maintain deployment pipelines and monitor infrastructure'.\n"
            "Compound Responsibilities: If all essential concepts are clearly demonstrated, mark MATCHED; if only a subset of critical concepts is shown without key deliverables, mark UNRESOLVED; if no meaningful execution proof exists, mark NO_MATCH. "
            "Merely listing a skill keyword in a skills list without experiential context is insufficient and must be marked UNRESOLVED or NO_MATCH.\n"
            "3. PROJECT requirements: Evaluate the candidate's actual projects (name, description, implementation, technologies). Do not judge projects solely by skill lists. "
            "Semantic matching of project domain/functionality is permitted if evidence supports it.\n"
            "4. SPECIFIC DISTINCTIONS (ANTI-HALLUCINATION):\n"
            "   - Generic 'authentication' or 'login' does NOT satisfy 'Basic Authentication' (mark UNRESOLVED unless HTTP Basic Auth is explicitly stated).\n"
            "   - Database mention (e.g. MongoDB) does NOT satisfy 'CRUD operations' (mark UNRESOLVED or NO_MATCH unless create, read, update, delete operations/APIs are described).\n"
            "   - Tool mention (e.g. GitHub) does NOT satisfy CI/CD pipeline automation (e.g. GitHub Actions) unless pipeline execution is described.\n"
            "   - Cross-requirement contamination is forbidden: each requirement must be evaluated strictly on its own merits.\n\n"
            "EVIDENCE CITATION RULE:\n"
            "- For MATCHED status: You MUST cite one or more valid evidence_ids from the supplied evidence that directly justify the match.\n"
            "- Never invent evidence_ids not present in the input.\n\n"
            "OUTPUT FORMAT:\n"
            "Return JSON matching: {\"verdicts\":[{\"requirement_id\":\"string\",\"status\":\"MATCHED|NO_MATCH|UNRESOLVED\",\"confidence\":0.0-1.0,\"evidence_ids\":[\"string\"],\"reasoning\":\"string\"}]}"
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

    async def match(self, job: Any, resume: Any, extracted: Any, config: Any) -> tuple[Any, list[MatchVerdict]]:
        requirements = RequirementBuilder.build(job, config)
        evidence = EvidenceBuilder.build(extracted)
        deterministic = [self.matcher.match(item, resume, evidence) for item in requirements]
        prefilter = EvidencePrefilter(
            self.settings.HYBRID_MATCHING_KEYWORD_OVERLAP_THRESHOLD,
            self.settings.HYBRID_MATCHING_MAX_EVIDENCE_PER_REQUIREMENT,
        )
        contextual = {item.requirement_id: item for item in requirements if item.kind in _CONTEXTUAL}
        supplied: dict[str, Evidence] = {}
        allowed_evidence: dict[str, set[str]] = {}
        unresolved: list[Requirement] = []

        for verdict in deterministic:
            requirement = contextual.get(verdict.requirement_id)
            if not requirement:
                continue
            # Rule 1: Deterministic MATCHED requirements MUST NOT be sent to LLM
            if verdict.status == MatchStatus.MATCHED:
                continue
            # Rule 2: Deterministic UNMET (NO_MATCH) or UNRESOLVED requirements MUST be sent to LLM if evidence exists
            selected = prefilter.select(requirement, evidence)
            if selected or requirement.kind == RequirementKind.RESPONSIBILITY:
                unresolved.append(requirement)
                if selected:
                    supplied.update((item.evidence_id, item) for item in selected)
                    allowed_evidence[requirement.requirement_id] = {item.evidence_id for item in selected}
                else:
                    allowed_evidence[requirement.requirement_id] = set()
            else:
                allowed_evidence[requirement.requirement_id] = set()

        llm = await self.evaluator.evaluate(unresolved, list(supplied.values()), allowed_evidence) if unresolved else []
        llm_by_id = {item.requirement_id: item for item in llm}
        fused = [llm_by_id.get(item.requirement_id, item) for item in deterministic]
        projects = EvidenceBuilder._projects(extracted)
        for project in projects:
            project["technologies"] = list(project.get("technologies") or [])
        requirement_by_id = {item.requirement_id: item for item in requirements}
        for verdict in fused:
            requirement = requirement_by_id.get(verdict.requirement_id)
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
        counts = {status.value: sum(v.status == status for v in fused) for status in MatchStatus}
        logger.info("hybrid_requirement_matching_completed", requirement_count=len(requirements), **counts)
        logger.info("hybrid_llm_decisions_validated", requested_count=len(unresolved), accepted_count=sum(v.method == MatchMethod.LLM_CONFIRMED for v in fused))
        return enriched, fused
