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
from uuid import UUID

# pyrefly: ignore [missing-import]
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
from app.services.jd_extraction_service import ExtractedJDNotFoundException, _is_valid_skill, _canonicalize_skill_name

logger = structlog.get_logger(__name__)

RULESET_VERSION = "1.0"

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
    """Deduplicate and canonicalize skills preserving original display casing and list order, filtering out invalid terms."""
    changes: list[NormalizationChange] = []
    seen: dict[str, str] = {}
    for skill in raw_skills:
        cleaned = re.sub(r"\s+", " ", skill).strip()
        if not cleaned or not _is_valid_skill(cleaned):
            continue
        canonical = _canonicalize_skill_name(cleaned)
        key = canonical.casefold()
        if key not in seen:
            seen[key] = canonical
            if canonical != cleaned:
                changes.append(NormalizationChange(
                    field="skills",
                    source=cleaned,
                    canonical=canonical,
                    rule="skill_canonical_map",
                ))
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
        if cleaned and _is_valid_skill(cleaned):
            canonical = _canonicalize_skill_name(cleaned)
            key = canonical.casefold()
            if key not in seen:
                seen.add(key)
                result.append(canonical)
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
        required_skills = _stable_casefold(_safe_list(extracted, "required_skills"))
        preferred_skills = _stable_casefold(_safe_list(extracted, "preferred_skills"))
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

        # ── Keywords ────────────────────────────────────────────
        canonical_keywords = _canonicalize_keywords(extracted.keywords or [])
        responsibilities = [r.strip() for r in (extracted.responsibilities or []) if r.strip()]
        certifications = _stable_casefold(_safe_list(extracted, "certifications"))
        education_disciplines = _stable_casefold(_safe_list(extracted, "education_disciplines"))
        job_title_value = getattr(extracted, "job_title", None)
        job_title = job_title_value.strip() if isinstance(job_title_value, str) else None
        if job_title and job_title.isupper():
            job_title = job_title.title()

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
