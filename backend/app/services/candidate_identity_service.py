from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.document import DocumentModel, DocumentTypeEnum
from app.models.extracted_info import ExtractedResumeModel
from app.models.normalized_info import NormalizedResumeModel
from app.schemas.candidate_identity import (
    CandidateIdentityInput,
    CandidateIdentityMatchResult,
    CandidateIdentityRecord,
    CandidateIdentityStatus,
    IdentityMatchMethod,
)
from app.services.pipeline.identity_rules import (
    normalize_candidate_identity,
    normalize_candidate_name,
    normalize_email_address,
    normalize_phone_number,
)

logger = structlog.get_logger(__name__)


def are_names_conflicting(name1: str | None, name2: str | None) -> bool:
    """Deterministic check for whether two candidate names conflict.

    Returns True ONLY when there is positive evidence of two different people
    (e.g. 'John Doe' vs 'Alice Smith', 'Rahul Sharma' vs 'Priya Patel').

    Returns False if names are compatible, identical, subset/extension
    (e.g. 'Arun Kumar' vs 'Arun Kumar K.', 'Harshini CS' vs 'Harshini'),
    or if either name is missing/unusable.
    """
    if not name1 or not name2:
        return False

    can1, meta1 = normalize_candidate_name(name1)
    can2, meta2 = normalize_candidate_name(name2)

    if not can1 or not can2 or not meta1.get("is_valid") or not meta2.get("is_valid"):
        return False

    if can1.casefold() == can2.casefold():
        return False

    words1 = [w.casefold() for w in can1.split()]
    words2 = [w.casefold() for w in can2.split()]
    set1 = set(words1)
    set2 = set(words2)

    # If one name is a clean subset of the other (e.g. 'Arun Kumar' in 'Arun Kumar K')
    if set1.issubset(set2) or set2.issubset(set1):
        return False

    # Check for single initial differences: e.g. 'John F. Kennedy' vs 'John Kennedy'
    non_initials1 = {w for w in words1 if len(w.strip(".")) > 1}
    non_initials2 = {w for w in words2 if len(w.strip(".")) > 1}
    if non_initials1 and non_initials2 and (non_initials1.issubset(non_initials2) or non_initials2.issubset(non_initials1)):
        return False

    # If first names match and last names match, but middle name/initial is extra
    if len(words1) >= 2 and len(words2) >= 2:
        if words1[0] == words2[0] and words1[-1] == words2[-1]:
            return False

    # If there is zero word overlap between multi-character words -> definite conflict
    intersection = non_initials1.intersection(non_initials2)
    if not intersection:
        return True

    # If primary first names disagree completely (e.g. 'Alice Smith' vs 'Bob Smith')
    if words1[0] != words2[0]:
        return True

    return False


class CandidateIdentityService:
    """Phase 2 Deterministic Candidate Identity Matching Engine.

    Determines whether an uploaded resume belongs to an existing ATS candidate,
    represents a new candidate, or requires manual identity review.
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def match_identity(
        self,
        candidate_input: CandidateIdentityInput | dict[str, Any],
        *,
        existing_records: list[CandidateIdentityRecord] | None = None,
        exclude_document_id: UUID | str | None = None,
    ) -> CandidateIdentityMatchResult:
        """Execute deterministic identity matching rules 1-5."""
        if isinstance(candidate_input, dict):
            input_data = CandidateIdentityInput(**candidate_input)
        else:
            input_data = candidate_input

        # Phase 1: Normalize input identity
        normalized = normalize_candidate_identity(
            candidate_name=input_data.candidate_name,
            email=input_data.email,
            phone=input_data.phone,
        )

        norm_name = normalized["candidate_name"]
        norm_email = normalized["email"]
        norm_phone = normalized["phone"]
        email_valid = normalized["identity_metadata"]["email"]["is_valid"]
        phone_valid = normalized["identity_metadata"]["phone"]["is_valid"]

        clean_zoho_id: str | None = None
        if input_data.zoho_candidate_id:
            raw_zid = str(input_data.zoho_candidate_id).strip()
            # Guard against treating attachment ID as candidate ID
            if raw_zid and raw_zid != str(input_data.zoho_attachment_id or "").strip():
                clean_zoho_id = raw_zid

        exclude_id_str = str(exclude_document_id or input_data.document_id or "")

        # ----------------------------------------------------------------------
        # Rule 1: Zoho Candidate ID
        # ----------------------------------------------------------------------
        if clean_zoho_id:
            matched_by_zoho = await self._find_by_zoho_candidate_id(
                clean_zoho_id,
                existing_records=existing_records,
                exclude_document_id=exclude_id_str,
            )
            if matched_by_zoho:
                # Check for conflicting candidate names under the same Zoho Candidate ID
                conflicts: list[dict[str, Any]] = []
                for rec in matched_by_zoho:
                    if are_names_conflicting(norm_name, rec.candidate_name):
                        conflicts.append({
                            "type": "NAME_CONFLICT_ON_ZOHO_ID",
                            "incoming_name": norm_name,
                            "existing_name": rec.candidate_name,
                            "existing_document_id": str(rec.document_id),
                            "zoho_candidate_id": clean_zoho_id,
                        })

                if conflicts:
                    return CandidateIdentityMatchResult(
                        status=CandidateIdentityStatus.REVIEW_REQUIRED,
                        matched_candidate_id=str(matched_by_zoho[0].document_id),
                        match_method=IdentityMatchMethod.ZOHO_CANDIDATE_ID,
                        confidence=0.5,
                        reasons=[
                            f"Zoho Candidate ID '{clean_zoho_id}' matched existing record(s), "
                            f"but candidate name '{norm_name}' conflicts with existing candidate name '{matched_by_zoho[0].candidate_name}'."
                        ],
                        conflicts=conflicts,
                        normalized_identity=normalized,
                    )

                # Valid, consistent match by Zoho Candidate ID
                return CandidateIdentityMatchResult(
                    status=CandidateIdentityStatus.EXISTING_CANDIDATE,
                    matched_candidate_id=str(matched_by_zoho[0].document_id),
                    match_method=IdentityMatchMethod.ZOHO_CANDIDATE_ID,
                    confidence=1.0,
                    reasons=[f"Matched existing candidate via Zoho Candidate ID: {clean_zoho_id}"],
                    conflicts=[],
                    normalized_identity=normalized,
                )
            # If Zoho ID is unmapped, do not automatically create duplicate: proceed to email & phone

        # ----------------------------------------------------------------------
        # Rule 2: Normalized Email
        # ----------------------------------------------------------------------
        if email_valid and norm_email:
            matched_by_email = await self._find_by_email(
                norm_email,
                existing_records=existing_records,
                exclude_document_id=exclude_id_str,
            )
            if matched_by_email:
                conflicts = []

                # Check if multiple existing records associated with this email have conflicting names
                distinct_names = {
                    normalize_candidate_name(r.candidate_name)[0]
                    for r in matched_by_email
                    if r.candidate_name
                }
                distinct_names.discard(None)
                if len(distinct_names) > 1:
                    name_list = sorted(list(distinct_names))
                    if any(are_names_conflicting(name_list[0], other) for other in name_list[1:]):
                        conflicts.append({
                            "type": "MULTIPLE_CONFLICTING_NAMES_ON_EMAIL",
                            "names": name_list,
                            "email": norm_email,
                        })

                # Check name conflicts between incoming candidate and existing records
                for rec in matched_by_email:
                    if are_names_conflicting(norm_name, rec.candidate_name):
                        conflicts.append({
                            "type": "NAME_CONFLICT_ON_EMAIL",
                            "incoming_name": norm_name,
                            "existing_name": rec.candidate_name,
                            "existing_document_id": str(rec.document_id),
                            "email": norm_email,
                        })

                # Check conflicting Zoho Candidate IDs
                if clean_zoho_id:
                    for rec in matched_by_email:
                        if rec.zoho_candidate_id and rec.zoho_candidate_id != clean_zoho_id:
                            conflicts.append({
                                "type": "ZOHO_ID_CONFLICT_ON_EMAIL",
                                "incoming_zoho_id": clean_zoho_id,
                                "existing_zoho_id": rec.zoho_candidate_id,
                                "existing_document_id": str(rec.document_id),
                                "email": norm_email,
                            })

                if conflicts:
                    return CandidateIdentityMatchResult(
                        status=CandidateIdentityStatus.REVIEW_REQUIRED,
                        matched_candidate_id=str(matched_by_email[0].document_id),
                        match_method=IdentityMatchMethod.NORMALIZED_EMAIL,
                        confidence=0.4 if any(c["type"] == "MULTIPLE_CONFLICTING_NAMES_ON_EMAIL" for c in conflicts) else 0.5,
                        reasons=[
                            f"Normalized email '{norm_email}' matched existing candidate record(s), "
                            f"but conflicting identity data was detected."
                        ],
                        conflicts=conflicts,
                        normalized_identity=normalized,
                    )

                # Exactly one consistent candidate identity matched by email
                return CandidateIdentityMatchResult(
                    status=CandidateIdentityStatus.EXISTING_CANDIDATE,
                    matched_candidate_id=str(matched_by_email[0].document_id),
                    match_method=IdentityMatchMethod.NORMALIZED_EMAIL,
                    confidence=0.95,
                    reasons=[f"Matched existing candidate via normalized email: {norm_email}"],
                    conflicts=[],
                    normalized_identity=normalized,
                )

        # ----------------------------------------------------------------------
        # Rule 3: Normalized Phone
        # ----------------------------------------------------------------------
        if phone_valid and norm_phone:
            matched_by_phone = await self._find_by_phone(
                norm_phone,
                existing_records=existing_records,
                exclude_document_id=exclude_id_str,
            )
            if matched_by_phone:
                conflicts = []

                # Check for multiple distinct candidates sharing this phone number
                distinct_emails = {
                    normalize_email_address(r.email)[0]
                    for r in matched_by_phone
                    if r.email
                }
                distinct_emails.discard(None)

                distinct_names = {
                    normalize_candidate_name(r.candidate_name)[0]
                    for r in matched_by_phone
                    if r.candidate_name
                }
                distinct_names.discard(None)

                if len(distinct_emails) > 1 or len(distinct_names) > 1:
                    return CandidateIdentityMatchResult(
                        status=CandidateIdentityStatus.REVIEW_REQUIRED,
                        matched_candidate_id=str(matched_by_phone[0].document_id),
                        match_method=IdentityMatchMethod.NORMALIZED_PHONE,
                        confidence=0.4,
                        reasons=[
                            f"Normalized phone '{norm_phone}' is shared across multiple distinct candidate records."
                        ],
                        conflicts=[{
                            "type": "SHARED_PHONE_NUMBER",
                            "phone": norm_phone,
                            "emails": sorted(list(distinct_emails)),
                            "names": sorted(list(distinct_names)),
                        }],
                        normalized_identity=normalized,
                    )

                # Check name conflict between incoming candidate and phone match
                for rec in matched_by_phone:
                    if are_names_conflicting(norm_name, rec.candidate_name):
                        conflicts.append({
                            "type": "NAME_CONFLICT_ON_PHONE",
                            "incoming_name": norm_name,
                            "existing_name": rec.candidate_name,
                            "existing_document_id": str(rec.document_id),
                            "phone": norm_phone,
                        })

                if conflicts:
                    return CandidateIdentityMatchResult(
                        status=CandidateIdentityStatus.REVIEW_REQUIRED,
                        matched_candidate_id=str(matched_by_phone[0].document_id),
                        match_method=IdentityMatchMethod.NORMALIZED_PHONE,
                        confidence=0.4,
                        reasons=[
                            f"Phone '{norm_phone}' matches existing candidate, "
                            f"but candidate names conflict ('{norm_name}' vs '{matched_by_phone[0].candidate_name}')."
                        ],
                        conflicts=conflicts,
                        normalized_identity=normalized,
                    )

                # If phone matches, check whether name provides supporting confirmation
                rec_name_norm = normalize_candidate_name(matched_by_phone[0].candidate_name)[0]
                if norm_name and rec_name_norm and not are_names_conflicting(norm_name, rec_name_norm):
                    return CandidateIdentityMatchResult(
                        status=CandidateIdentityStatus.EXISTING_CANDIDATE,
                        matched_candidate_id=str(matched_by_phone[0].document_id),
                        match_method=IdentityMatchMethod.NORMALIZED_PHONE,
                        confidence=0.85,
                        reasons=[
                            f"Matched existing candidate via normalized phone: {norm_phone} with supporting name match."
                        ],
                        conflicts=[],
                        normalized_identity=normalized,
                    )

                # Phone matches but no name confirmation on one/both sides -> ambiguous
                return CandidateIdentityMatchResult(
                    status=CandidateIdentityStatus.REVIEW_REQUIRED,
                    matched_candidate_id=str(matched_by_phone[0].document_id),
                    match_method=IdentityMatchMethod.NORMALIZED_PHONE,
                    confidence=0.5,
                    reasons=[
                        f"Phone '{norm_phone}' matches an existing candidate, but name confirmation is insufficient."
                    ],
                    conflicts=[{
                        "type": "AMBIGUOUS_PHONE_MATCH_WITHOUT_NAME",
                        "phone": norm_phone,
                        "incoming_name": norm_name,
                        "existing_name": matched_by_phone[0].candidate_name,
                    }],
                    normalized_identity=normalized,
                )

        # ----------------------------------------------------------------------
        # Rule 4 & 5: New Candidate vs Insufficient Information
        # ----------------------------------------------------------------------
        # Check if we had reliable contact information to perform identity resolution
        has_reliable_contact = bool(email_valid and norm_email) or bool(phone_valid and norm_phone)

        # Missing contact information alone must not be treated as proof that a candidate is new
        if not has_reliable_contact and not clean_zoho_id:
            return CandidateIdentityMatchResult(
                status=CandidateIdentityStatus.REVIEW_REQUIRED,
                matched_candidate_id=None,
                match_method=IdentityMatchMethod.NONE,
                confidence=0.0,
                reasons=[
                    "Missing or invalid contact information (email and phone). "
                    "Missing contact information alone cannot prove that a candidate is new."
                ],
                conflicts=[{
                    "type": "INSUFFICIENT_IDENTITY_DATA",
                    "email_status": normalized["identity_metadata"]["email"].get("reason"),
                    "phone_status": normalized["identity_metadata"]["phone"].get("reason"),
                }],
                normalized_identity=normalized,
            )

        # Reliable identity evidence was present, checked against existing ATS records,
        # and no existing candidate or unresolved conflicts were found.
        return CandidateIdentityMatchResult(
            status=CandidateIdentityStatus.NEW_CANDIDATE,
            matched_candidate_id=None,
            match_method=IdentityMatchMethod.NONE,
            confidence=1.0,
            reasons=["Reliable identity evidence checked against existing ATS records with no matches found."],
            conflicts=[],
            normalized_identity=normalized,
        )

    # ==========================================================================
    # Database / In-Memory Query Helpers
    # ==========================================================================

    async def _find_by_zoho_candidate_id(
        self,
        zoho_candidate_id: str,
        existing_records: list[CandidateIdentityRecord] | None = None,
        exclude_document_id: str = "",
    ) -> list[CandidateIdentityRecord]:
        """Find candidate records matching Zoho Candidate ID."""
        if existing_records is not None:
            return [
                r for r in existing_records
                if str(r.document_id) != exclude_document_id
                and r.zoho_candidate_id
                and str(r.zoho_candidate_id).strip() == zoho_candidate_id
            ]

        if self.session is None:
            return []

        stmt = (
            select(DocumentModel)
            .options(
                selectinload(DocumentModel.normalized_resume),
                selectinload(DocumentModel.extracted_resume),
            )
            .where(
                DocumentModel.document_type == DocumentTypeEnum.RESUME,
                DocumentModel.deleted_at.is_(None),
                DocumentModel.metadata_json["zoho_candidate_id"].as_string() == zoho_candidate_id,
            )
        )
        if exclude_document_id:
            try:
                stmt = stmt.where(DocumentModel.id != UUID(exclude_document_id))
            except ValueError:
                pass

        docs = (await self.session.scalars(stmt)).all()
        return [self._doc_to_record(d) for d in docs]

    async def _find_by_email(
        self,
        normalized_email: str,
        existing_records: list[CandidateIdentityRecord] | None = None,
        exclude_document_id: str = "",
    ) -> list[CandidateIdentityRecord]:
        """Find candidate records matching normalized email."""
        if existing_records is not None:
            results = []
            for r in existing_records:
                if str(r.document_id) == exclude_document_id:
                    continue
                norm, _ = normalize_email_address(r.email)
                if norm and norm == normalized_email:
                    results.append(r)
            return results

        if self.session is None:
            return []

        stmt = (
            select(DocumentModel)
            .options(
                selectinload(DocumentModel.normalized_resume),
                selectinload(DocumentModel.extracted_resume),
            )
            .outerjoin(NormalizedResumeModel, NormalizedResumeModel.document_id == DocumentModel.id)
            .outerjoin(ExtractedResumeModel, ExtractedResumeModel.document_id == DocumentModel.id)
            .where(
                DocumentModel.document_type == DocumentTypeEnum.RESUME,
                DocumentModel.deleted_at.is_(None),
                or_(
                    NormalizedResumeModel.email == normalized_email,
                    ExtractedResumeModel.email == normalized_email,
                    DocumentModel.metadata_json["email"].as_string() == normalized_email,
                ),
            )
        )
        if exclude_document_id:
            try:
                stmt = stmt.where(DocumentModel.id != UUID(exclude_document_id))
            except ValueError:
                pass

        docs = (await self.session.scalars(stmt)).all()
        return [self._doc_to_record(d) for d in docs]

    async def _find_by_phone(
        self,
        normalized_phone: str,
        existing_records: list[CandidateIdentityRecord] | None = None,
        exclude_document_id: str = "",
    ) -> list[CandidateIdentityRecord]:
        """Find candidate records matching normalized phone number."""
        if existing_records is not None:
            results = []
            for r in existing_records:
                if str(r.document_id) == exclude_document_id:
                    continue
                norm, _ = normalize_phone_number(r.phone)
                if norm and norm == normalized_phone:
                    results.append(r)
            return results

        if self.session is None:
            return []

        stmt = (
            select(DocumentModel)
            .options(
                selectinload(DocumentModel.normalized_resume),
                selectinload(DocumentModel.extracted_resume),
            )
            .outerjoin(NormalizedResumeModel, NormalizedResumeModel.document_id == DocumentModel.id)
            .outerjoin(ExtractedResumeModel, ExtractedResumeModel.document_id == DocumentModel.id)
            .where(
                DocumentModel.document_type == DocumentTypeEnum.RESUME,
                DocumentModel.deleted_at.is_(None),
                or_(
                    NormalizedResumeModel.phone == normalized_phone,
                    ExtractedResumeModel.phone == normalized_phone,
                    DocumentModel.metadata_json["phone"].as_string() == normalized_phone,
                ),
            )
        )
        if exclude_document_id:
            try:
                stmt = stmt.where(DocumentModel.id != UUID(exclude_document_id))
            except ValueError:
                pass

        docs = (await self.session.scalars(stmt)).all()
        return [self._doc_to_record(d) for d in docs]

    @staticmethod
    def _doc_to_record(doc: DocumentModel) -> CandidateIdentityRecord:
        meta = doc.metadata_json or {}
        name = (
            meta.get("candidate_name")
            or (doc.extracted_resume.candidate_name if doc.extracted_resume else None)
        )
        email = (
            (doc.normalized_resume.email if doc.normalized_resume else None)
            or meta.get("email")
            or (doc.extracted_resume.email if doc.extracted_resume else None)
        )
        phone = (
            (doc.normalized_resume.phone if doc.normalized_resume else None)
            or meta.get("phone")
            or (doc.extracted_resume.phone if doc.extracted_resume else None)
        )
        return CandidateIdentityRecord(
            document_id=doc.id,
            candidate_name=name,
            email=email,
            phone=phone,
            zoho_candidate_id=meta.get("zoho_candidate_id"),
            zoho_candidate_number=meta.get("zoho_candidate_number"),
            zoho_attachment_id=meta.get("zoho_attachment_id"),
        )
