"""
JD Normalization Service
========================
Consumes ExtractedJDModel to produce a canonical, deduplicated, and
standardized set of requirements for downstream matching and scoring.
No external dependencies — rule-based, version-tracked.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from time import perf_counter
from typing import Sequence
from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, ConflictException, InternalServerException
from app.repositories.document_repository import DocumentRepository
from app.repositories.extracted_jd_repository import ExtractedJDRepository
from app.repositories.normalized_jd_repository import NormalizedJDRepository
from app.schemas.document import DocumentType, ProcessingStage, ProcessingStatus
from app.schemas.normalized_jd import (
    CanonicalExperienceRequirement,
    JDNormalizeResult,
    NormalizationChange,
    NormalizationMetadata,
    NormalizedJDCreate,
    NormalizedJDRead,
)
from app.services.document_service import DocumentNotFoundException
from app.services.jd_extraction_service import ExtractedJDNotFoundException

logger = structlog.get_logger(__name__)

from app.services.pipeline.canonical_dictionaries import RULESET_VERSION

# ─── Degree canonicalization map ────────────────────────────────────────────

DEGREE_CANONICAL: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bph\.?d\b|\bdoctoral?\b|\bdoctorate\b", re.I), "Doctor of Philosophy (PhD)"),
    (re.compile(r"\bmba\b|\bmaster\s+of\s+business\b", re.I), "Master of Business Administration (MBA)"),
    (re.compile(r"\bmaster(?:'s)?\s+(?:of\s+)?(?:science|sc|s)\b|\bm\.?sc\b|\bm\.?s\b", re.I), "Master of Science"),
    (re.compile(r"\bmaster(?:'s)?\s+(?:of\s+)?(?:engineering|tech|technology)\b|\bm\.?tech\b|\bm\.?e\b", re.I), "Master of Engineering"),
    (re.compile(r"\bmaster(?:'s)?\b", re.I), "Master's Degree"),
    (re.compile(r"\bbachelor(?:'s)?\s+(?:of\s+)?(?:engineering|tech|technology)\b|\bb\.?tech\b|\bb\.?e\b", re.I), "Bachelor of Engineering"),
    (re.compile(r"\bbachelor(?:'s)?\s+(?:of\s+)?(?:science|sc|s)\b|\bb\.?sc\b|\bb\.?s\b", re.I), "Bachelor of Science"),
    (re.compile(r"\bbachelor(?:'s)?\b|\bundergraduate\b", re.I), "Bachelor's Degree"),
    (re.compile(r"\bassociate(?:'s)?\s+degree\b", re.I), "Associate Degree"),
]

# ─── Experience parsing ──────────────────────────────────────────────────────

_EXP_RANGE = re.compile(r"(\d+)\s*[-–to]+\s*(\d+)\s+years?", re.I)
_EXP_PLUS = re.compile(r"(\d+)\+\s*years?", re.I)
_EXP_MIN = re.compile(r"(?:minimum|at\s+least|min(?:imum)?\.?)\s+(?:of\s+)?(\d+)\s+years?", re.I)
_EXP_PLAIN = re.compile(r"(\d+)\s+years?", re.I)


def _parse_experience_phrase(phrase: str) -> CanonicalExperienceRequirement:
    """Convert a raw experience string to canonical min/max months."""
    m = _EXP_RANGE.search(phrase)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return CanonicalExperienceRequirement(
            minimum_months=lo * 12,
            maximum_months=hi * 12,
            display_value=phrase,
        )
    m = _EXP_PLUS.search(phrase)
    if m:
        yrs = int(m.group(1))
        return CanonicalExperienceRequirement(
            minimum_months=yrs * 12,
            maximum_months=None,
            display_value=phrase,
        )
    m = _EXP_MIN.search(phrase)
    if m:
        yrs = int(m.group(1))
        return CanonicalExperienceRequirement(
            minimum_months=yrs * 12,
            maximum_months=None,
            display_value=phrase,
        )
    m = _EXP_PLAIN.search(phrase)
    if m:
        yrs = int(m.group(1))
        return CanonicalExperienceRequirement(
            minimum_months=yrs * 12,
            maximum_months=None,
            display_value=phrase,
        )
    return CanonicalExperienceRequirement(
        minimum_months=None,
        maximum_months=None,
        display_value=phrase,
    )


# ─── Canonicalization helpers ────────────────────────────────────────────────

def _canonicalize_degree(raw: str) -> tuple[str, str]:
    """Return (canonical_name, rule_applied)."""
    for pattern, canonical in DEGREE_CANONICAL:
        if pattern.search(raw):
            return canonical, f"degree_map:{canonical}"
    return raw.strip(), "degree_map:passthrough"


def _canonicalize_skills(raw_skills: list[str]) -> tuple[list[str], list[NormalizationChange]]:
    """Deduplicate skills preserving original display casing and list order."""
    changes: list[NormalizationChange] = []
    seen: dict[str, str] = {}
    for skill in raw_skills:
        cleaned = re.sub(r"\s+", " ", skill).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key not in seen:
            seen[key] = cleaned
    return list(seen.values()), changes


def _canonicalize_keywords(raw_keywords: list[str]) -> list[str]:
    """Deduplicate keyword values case-insensitively without concatenating them."""
    seen: set[str] = set()
    result: list[str] = []
    for kw in raw_keywords:
        cleaned = re.sub(r"\s+", " ", kw).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _safe_list(source: object, field: str) -> list[str]:
    value = getattr(source, field, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def _stable_casefold(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", value).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


# ─── JD skill-phrase normalisation helpers ──────────────────────────────────

# Strip qualifier prefixes from JD bullet text before skill lookup.
# Handles both standalone verb phrases AND adjective-prefixed ones, e.g.:
#   "Strong programming fundamentals in Java"  → "Java"
#   "Familiarity with Git and GitHub"           → "Git and GitHub"
#   "Basic SQL and database concepts"           → "SQL and database concepts"
#   "Hands-on experience with Docker"           → "Docker"
_PHRASE_FILLER_LEADERS = re.compile(
    r"^"
    # Optional leading adjective
    r"(?:(?:strong|solid|deep|basic|general|good|working)\s+)?"
    # Optional "programming" modifier (e.g. "programming fundamentals in")
    r"(?:programming\s+)?"
    # Verb / noun phrase — all common JD qualification phrases
    r"(?:"
    r"fundamentals?(?:\s+(?:in|of))?|"  # fundamentals in X / fundamentals of X
    r"exposure\s+to|"
    r"knowledge\s+of|"
    r"understanding\s+of|"
    r"familiarity\s+with|"
    r"experience\s+(?:in|with)|"
    r"proficiency\s+in|"
    r"hands[-\s]on\s+(?:experience\s+)?(?:in|with)?|"
    r"ability\s+to"
    r")\s+",
    re.I,
)
# Strip qualifier suffixes that add no skill meaning
_PHRASE_FILLER_TRAILERS = re.compile(
    r"\s+(?:concepts?|fundamentals?|programming|and\s+related\s+tools?|experience|knowledge|tools?)$",
    re.I,
)
# Items that are clearly requirement prose, not skill labels
_NON_SKILL_PATTERNS = re.compile(
    r"\b(?:"
    r"candidates?|graduates?|years?\s+of|experience\s+required|encouraged|willingness|"
    r"apply|teamwork|communication|analytical|problem[-\s]solving|focus|selection|"
    r"relevant|exposure|academic|personal|or\s+equivalent|requirements?\s+(?:configured|listed)|"
    r"another|any\s+(?:other|similar)|similar|equivalent"
    r")\b",
    re.I,
)
# Single generic words that add no matching value as standalone skills
_GENERIC_SINGLE_WORDS = frozenset({
    "ability", "communication", "teamwork", "focus", "selection",
    "relevant", "exposure", "academic", "personal", "another",
    "framework", "technology", "tool", "language", "system", "method",
})


def _atomize_skill_phrase(
    phrase: str,
    skill_aliases: dict[str, str],
    skills_vocab: frozenset[str],
) -> list[str]:
    """
    Convert a verbose JD skill phrase to one or more atomic canonical skill tokens.

    Algorithm (generalizable — NO hardcoded JD content):

    1. Direct alias lookup on the cleaned phrase.
    2. Strip qualifier leaders ("Strong programming fundamentals in", "Familiarity with", …)
       and trailer noise ("concepts", "experience", …).
    3. Direct alias lookup on the stripped form.
    4. Scan SKILL_ALIASES for whole-word embedded tokens (longest-first).
       Return immediately if any found — preserves compound phrases like
       "Data Structures and Algorithms" that are whole alias keys.
    5. Scan SKILLS_VOCABULARY for whole-word embedded tokens (longest-first).
       Return immediately if any found.
    6. Only if steps 1-5 produced nothing: split on " or " / " and " and recurse
       on each part (handles "MySQL or PostgreSQL", "Git and GitHub").
    7. Fallback: return stripped phrase if short (≤ 50 chars) and not noise.
    """
    cleaned = re.sub(r"\s+", " ", phrase).strip()
    if not cleaned:
        return []
    key = cleaned.casefold()

    # 1. Direct alias lookup
    if key in skill_aliases:
        return [skill_aliases[key]]

    # 2. Strip qualifier leaders/trailers
    stripped = _PHRASE_FILLER_LEADERS.sub("", cleaned).strip()
    stripped = _PHRASE_FILLER_TRAILERS.sub("", stripped).strip()
    # Also strip leading prepositions that the leaders may leave behind
    stripped = re.sub(r"^(?:in|of|with|for)\s+", "", stripped, flags=re.I).strip()
    stripped_key = stripped.casefold()

    # 3. Stripped alias lookup
    if stripped_key in skill_aliases:
        return [skill_aliases[stripped_key]]

    # 4. Scan SKILL_ALIASES: longest-match first so compound keys beat fragments.
    #    Important: this step runs BEFORE splitting on "and"/"or" so that
    #    "Data Structures and Algorithms" is matched as one unit, not split.
    found: list[str] = []
    found_keys: set[str] = set()
    lower_stripped = stripped_key
    for alias_key in sorted(skill_aliases, key=len, reverse=True):
        pattern = r"(?<![\w+#])" + re.escape(alias_key) + r"(?![\w+#])"
        if re.search(pattern, lower_stripped, re.I):
            canonical = skill_aliases[alias_key]
            ck = canonical.casefold()
            if ck not in found_keys:
                found_keys.add(ck)
                found.append(canonical)
    if found:
        return found

    # 5. Scan SKILLS_VOCABULARY: longest-match first (same reasoning as step 4).
    for vocab_token in sorted(skills_vocab, key=len, reverse=True):
        vk = vocab_token.casefold()
        pattern = r"(?<![\w+#])" + re.escape(vk) + r"(?![\w+#])"
        if re.search(pattern, lower_stripped, re.I):
            canonical = skill_aliases.get(vk, vocab_token)
            ck = canonical.casefold()
            if ck not in found_keys:
                found_keys.add(ck)
                found.append(canonical)
    if found:
        return found

    # 6. Split on " or " / " and " and recurse (only when steps 1-5 gave nothing).
    if re.search(r"\bor\b|\band\b", stripped, re.I):
        parts = re.split(r"\s+(?:or|and)\s+", stripped, flags=re.I)
        result: list[str] = []
        seen_rk: set[str] = set()
        for part in parts:
            for s in _atomize_skill_phrase(part.strip(), skill_aliases, skills_vocab):
                sk = s.casefold()
                if sk not in seen_rk:
                    seen_rk.add(sk)
                    result.append(s)
        if result:
            return result

    # 7. Fallback: return stripped phrase only when it looks like a real skill label.
    if (
        stripped
        and len(stripped) <= 50
        and not _NON_SKILL_PATTERNS.search(stripped)
        and stripped.casefold() not in _GENERIC_SINGLE_WORDS
    ):
        return [stripped]
    return []


def _is_skill_item(item: str) -> bool:
    """Return True only when the string looks like a genuine skill label, not prose."""
    stripped = item.strip()
    if len(stripped) < 2:
        return False
    # Long sentences are requirement prose, not skill labels
    if len(stripped) > 70:
        return False
    # Phrases that read as requirement / HR prose
    if _NON_SKILL_PATTERNS.search(stripped):
        return False
    # Single generic words that are not useful as standalone skills
    if stripped.casefold() in _GENERIC_SINGLE_WORDS:
        return False
    return True


def _normalize_skill_list(
    raw: list[str],
    skill_aliases: dict[str, str],
    skills_vocab: frozenset[str],
    *,
    filter_noise: bool = False,
) -> list[str]:
    """
    Convert a list of raw extracted JD skill entries to a clean list of atomic
    canonical skill tokens, optionally filtering prose items first.

    Args:
        raw:          Raw list from extracted_job_descriptions.required_skills or preferred_skills.
        skill_aliases: SKILL_ALIASES canonical map.
        skills_vocab:  SKILLS_VOCABULARY frozenset.
        filter_noise: When True, pre-filter items that are clearly non-skill prose
                      (used for preferred_skills which often contains HR sentences).
    """
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if filter_noise and not _is_skill_item(item):
            continue
        atoms = _atomize_skill_phrase(item, skill_aliases, skills_vocab)
        for atom in atoms:
            k = atom.casefold()
            if k and k not in seen:
                seen.add(k)
                result.append(atom)
    return result


# ─── Exceptions ─────────────────────────────────────────────────────────────

class DocumentNotNormalizableException(ConflictException):
    error_code = "DOCUMENT_NOT_NORMALIZABLE"
    default_message = "Document must be extracted before normalization."


class NormalizedJDNotFoundException(AppException):
    status_code = 404
    error_code = "NORMALIZED_JD_NOT_FOUND"
    default_message = "No normalization result was found for this document."


# ─── Service ────────────────────────────────────────────────────────────────

class JDNormalizationService:
    """Normalize structured extraction results into canonical JD requirements."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        extracted_repository: ExtractedJDRepository,
        normalized_repository: NormalizedJDRepository,
    ) -> None:
        self.document_repository = document_repository
        self.extracted_repository = extracted_repository
        self.normalized_repository = normalized_repository

    async def normalize_document(self, document_id: UUID) -> JDNormalizeResult:
        started_at = perf_counter()
        document = await self._load_document(document_id)
        logger.info(
            "[NORMALIZE] normalization started",
            document_id=str(document_id),
            document_type="JOB_DESCRIPTION",
        )

        # Load extracted data
        try:
            extracted = await self.extracted_repository.get_by_document_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve extracted data.") from exc

        if extracted is None:
            raise ExtractedJDNotFoundException(
                "Document must be extracted before normalization."
            )

        metadata = dict(document.metadata_json or {})
        changes: list[NormalizationChange] = []
        warnings: list[str] = []

        # ── Skills ──────────────────────────────────────────────
        from app.services.jd_extraction_service import SKILLS_VOCABULARY
        from app.services.pipeline.canonical_dictionaries import SKILL_ALIASES

        raw_required = _safe_list(extracted, "required_skills")
        raw_preferred = _safe_list(extracted, "preferred_skills")
        skills_vocab: frozenset[str] = frozenset(SKILLS_VOCABULARY)

        # Atomize verbose skill phrases → canonical atomic skill tokens (generalizable)
        required_skills = _normalize_skill_list(raw_required, SKILL_ALIASES, skills_vocab, filter_noise=False)
        # For preferred_skills also filter prose noise (e.g. "Candidate Requirements", "fresh graduates are encouraged...")
        preferred_skills = _normalize_skill_list(raw_preferred, SKILL_ALIASES, skills_vocab, filter_noise=True)

        # Remove preferred items that duplicated required
        req_keys = {s.casefold() for s in required_skills}
        preferred_skills = [s for s in preferred_skills if s.casefold() not in req_keys]

        grouped_skills = [*required_skills, *preferred_skills]
        canonical_skills, skill_changes = _canonicalize_skills(grouped_skills or list(extracted.skills or []))
        changes.extend(skill_changes)

        # ── Degrees ─────────────────────────────────────────────
        degree_requirements: list[str] = []
        for raw_degree in (extracted.education or []):
            canonical, rule = _canonicalize_degree(raw_degree)
            degree_requirements.append(canonical)
            if canonical != raw_degree:
                changes.append(NormalizationChange(
                    field="education",
                    source=raw_degree,
                    canonical=canonical,
                    rule=rule,
                ))
        # Deduplicate degrees
        seen_degrees: set[str] = set()
        unique_degrees: list[str] = []
        for d in degree_requirements:
            if d not in seen_degrees:
                seen_degrees.add(d)
                unique_degrees.append(d)
        degree_requirements = unique_degrees

        # ── Experience ──────────────────────────────────────────
        experience_requirements: list[CanonicalExperienceRequirement] = []
        seen_exp_keys: set[str] = set()
        for raw_exp in (extracted.experience or []):
            req = _parse_experience_phrase(raw_exp)
            exp_key = f"{req.minimum_months}:{req.maximum_months}:{req.display_value.casefold()}"
            if exp_key not in seen_exp_keys:
                seen_exp_keys.add(exp_key)
                experience_requirements.append(req)
                changes.append(NormalizationChange(
                    field="experience",
                    source=raw_exp,
                    canonical=req.display_value,
                    rule=f"experience_parse:months(min={req.minimum_months},max={req.maximum_months})",
                ))

        if not experience_requirements:
            warnings.append("No experience requirements found in extracted data.")

        # ── Job Title ───────────────────────────────────────────
        job_title_value = getattr(extracted, "job_title", None)
        job_title = job_title_value.strip() if isinstance(job_title_value, str) else None
        if job_title and job_title.isupper():
            job_title = job_title.title()

        # ── Keywords ────────────────────────────────────────────
        # Build keywords from the already-atomized technical skills, NOT the verbose
        # extraction phrases. This ensures that project-evidence scoring uses meaningful
        # technical tokens (e.g. "Java", "SQL") rather than verbose JD sentences.
        canonical_keywords = list(dict.fromkeys(
            ([job_title] if job_title else []) + required_skills + preferred_skills
        ))
        responsibilities = [r.strip() for r in (extracted.responsibilities or []) if r.strip()]
        certifications = _stable_casefold(_safe_list(extracted, "certifications"))
        education_disciplines = _stable_casefold(_safe_list(extracted, "education_disciplines"))

        # ── Domain passthrough ──────────────────────────────────
        domain = extracted.domain

        # ── Confidence estimation ────────────────────────────────
        field_confidence = {
            "skills": extracted.confidence_scores.get("skills", 0.0),
            "education": extracted.confidence_scores.get("education", 0.0),
            "experience": extracted.confidence_scores.get("experience", 0.0),
            "certifications": extracted.confidence_scores.get("certifications", 0.0),
        }

        norm_meta = NormalizationMetadata(
            ruleset_version=RULESET_VERSION,
            normalized_at=datetime.now(UTC).isoformat(),
            changes=changes,
            warnings=warnings,
            field_confidence=field_confidence,
        )

        payload = NormalizedJDCreate(
            document_id=document_id,
            extracted_job_description_id=extracted.id,
            skills=canonical_skills,
            job_title=job_title,
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            degree_requirements=degree_requirements,
            education_disciplines=education_disciplines,
            experience_requirements=experience_requirements,
            domain=domain,
            keywords=canonical_keywords,
            responsibilities=responsibilities,
            certifications=certifications,
            normalization_metadata=norm_meta,
            ruleset_version=RULESET_VERSION,
        )

        try:
            await self.normalized_repository.upsert(
                payload, commit=False, refresh=False
            )
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to persist normalization result.") from exc

        # Update document status to COMPLETED / NORMALIZATION stage
        await self._set_status(
            document_id,
            ProcessingStatus.COMPLETED,
            {**metadata, "normalization_stage": "NORMALIZATION", "extraction_error": None},
            refresh=False,
            document=document,
        )

        logger.info(
            "[NORMALIZE] normalization completed",
            document_id=str(document_id),
            document_type="JOB_DESCRIPTION",
            canonical_skills=len(canonical_skills),
            responsibilities_count=len(responsibilities),
            certifications_count=len(certifications),
            degrees=len(degree_requirements),
            experience_reqs=len(experience_requirements),
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        return JDNormalizeResult(
            document_id=document_id,
            document_type=DocumentType.JOB_DESCRIPTION,
            processing_stage=ProcessingStage.NORMALIZATION,
            processing_status=ProcessingStatus.COMPLETED,
            ruleset_version=RULESET_VERSION,
            message=(
                f"Normalized {len(canonical_skills)} skills, "
                f"{len(degree_requirements)} degree requirements, "
                f"{len(experience_requirements)} experience requirements."
            ),
        )

    async def get_normalized_document(self, document_id: UUID) -> NormalizedJDRead:
        await self._load_document(document_id)
        try:
            normalized = await self.normalized_repository.get_by_document_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve normalization result.") from exc
        if normalized is None:
            raise NormalizedJDNotFoundException()
        return NormalizedJDRead.from_orm_model(normalized)

    async def _load_document(self, document_id: UUID):
        try:
            document = await self.document_repository.get_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None:
            raise DocumentNotFoundException()
        return document

    async def _set_status(
        self,
        document_id: UUID,
        status: ProcessingStatus,
        metadata: dict,
        *,
        commit: bool = True,
        refresh: bool = True,
        document=None,
    ):
        try:
            updated = await self.document_repository.update_status(
                document_id,
                status,
                metadata,
                commit=commit,
                refresh=refresh,
                document=document,
            )
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to update document status.") from exc
        if updated is None:
            raise DocumentNotFoundException()
        return updated
