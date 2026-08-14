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
    Evidence, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict,
    Requirement, RequirementKind,
)
from app.services.pipeline.canonical_dictionaries import (
    CERTIFICATION_ALIASES, DEGREE_ALIASES, LANGUAGE_ALIASES, SKILL_ALIASES,
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
    """Convert the existing normalized JD into stable requirement objects."""

    @staticmethod
    def build(job: Any, config: Any) -> list[Requirement]:
        rows: list[tuple[RequirementKind, str, bool, bool]] = []
        mandatory = {_key(value) for value in (getattr(config, "mandatory_skills", None) or [])}
        preferred = {_key(value) for value in (getattr(job, "preferred_skills", None) or [])}
        for value in getattr(job, "skills", None) or []:
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
                if required_key in canonical or required_key == _key(item.text):
                    return MatchVerdict(
                        requirement_id=requirement.requirement_id,
                        status=MatchStatus.MATCHED, confidence=1,
                        evidence_ids=[item.evidence_id],
                        reasoning="Contextual evidence contains the exact canonical requirement.",
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
            candidates = [item.get("degree") for item in (getattr(resume, "education", None) or []) if item.get("degree")]
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
        # Fallback to available evidence items so LLM can perform semantic review
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
            if not requirement or verdict.status != MatchStatus.UNRESOLVED:
                continue
            selected = prefilter.select(requirement, evidence)
            if selected:
                unresolved.append(requirement)
                supplied.update((item.evidence_id, item) for item in selected)
                allowed_evidence[requirement.requirement_id] = {item.evidence_id for item in selected}
            else:
                verdict.status = MatchStatus.NO_MATCH
                verdict.confidence = 1
                verdict.reasoning = "No deterministically relevant evidence was found."
        llm = await self.evaluator.evaluate(unresolved, list(supplied.values()), allowed_evidence)
        llm_by_id = {item.requirement_id: item for item in llm}
        fused = [llm_by_id.get(item.requirement_id, item) for item in deterministic]
        projects = EvidenceBuilder._projects(extracted)
        for project in projects:
            project["technologies"] = list(project.get("technologies") or [])
        requirement_by_id = {item.requirement_id: item for item in requirements}
        for verdict in fused:
            requirement = requirement_by_id[verdict.requirement_id]
            if verdict.status != MatchStatus.MATCHED or requirement.kind != RequirementKind.PROJECT_RELEVANCE:
                continue
            for evidence_id in verdict.evidence_ids:
                if not evidence_id.startswith("project:"):
                    continue
                index = int(evidence_id.split(":", 1)[1]) - 1
                if 0 <= index < len(projects):
                    technologies = projects[index].setdefault("technologies", [])
                    if _key(requirement.text) not in {_key(value) for value in technologies}:
                        technologies.append(requirement.text)
        enriched = SimpleNamespace(projects=projects)
        counts = {status.value: sum(v.status == status for v in fused) for status in MatchStatus}
        logger.info("hybrid_requirement_matching_completed", requirement_count=len(requirements), **counts)
        logger.info("hybrid_llm_decisions_validated", requested_count=len(unresolved), accepted_count=sum(v.method == MatchMethod.LLM_CONFIRMED for v in fused))
        return enriched, fused
