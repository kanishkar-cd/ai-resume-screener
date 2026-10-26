from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.document import DocumentModel, DocumentTypeEnum
from app.models.extracted_info import ExtractedResumeModel
from app.models.normalized_info import NormalizedResumeModel
from app.models.project import ProjectModel
from app.schemas.candidate_identity import (
    CandidateIdentityInput,
    CandidateIdentityRecord,
    CandidateIdentityStatus,
)
from app.schemas.repeat_application import (
    ApplicationHistoryItem,
    RepeatApplicationInput,
    RepeatApplicationResult,
    RepeatApplicationStatus,
)
from app.services.candidate_identity_service import CandidateIdentityService
from app.services.pipeline.identity_rules import (
    normalize_candidate_identity,
    normalize_email_address,
    normalize_phone_number,
)

logger = structlog.get_logger(__name__)


class RepeatApplicationService:
    """Phase 3 Deterministic Repeat Application Detection Engine.

    Detects whether an identified candidate has applied to multiple job openings
    in the ATS, while strictly avoiding false positives from re-uploads,
    re-processing runs, or multiple resume attachments for a single application.
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        identity_service: CandidateIdentityService | None = None,
    ) -> None:
        self.session = session
        self.identity_service = identity_service or CandidateIdentityService(session)

    async def detect_repeat_application(
        self,
        application_input: RepeatApplicationInput | dict[str, Any],
        *,
        existing_records: list[CandidateIdentityRecord] | None = None,
        existing_applications: list[ApplicationHistoryItem] | None = None,
    ) -> RepeatApplicationResult:
        """Execute deterministic repeat-application detection rules 1-4."""
        if isinstance(application_input, dict):
            inp = RepeatApplicationInput(**application_input)
        else:
            inp = application_input

        # ----------------------------------------------------------------------
        # Rule 2: Identify the current job opening
        # ----------------------------------------------------------------------
        current_job_id: str | None = None
        if inp.job_opening_id and str(inp.job_opening_id).strip():
            current_job_id = str(inp.job_opening_id).strip()

        current_proj_id: str | None = None
        if inp.project_id:
            current_proj_id = str(inp.project_id).strip()

        # If manual upload or import has no associated job opening or project
        if not current_job_id and not current_proj_id:
            return RepeatApplicationResult(
                status=RepeatApplicationStatus.JOB_OPENING_REQUIRED,
                is_repeat=False,
                candidate_id=None,
                zoho_candidate_id=None,
                current_job_opening_id=None,
                current_project_id=None,
                total_previous_applications=0,
                previous_applications=[],
                identity_match_result=None,
                reasons=[
                    "The current job opening cannot be determined. "
                    "Repeat-application detection cannot proceed without an associated job opening or project."
                ],
            )

        # ----------------------------------------------------------------------
        # Rule 1: Resolve candidate identity using Phase 2 matching engine
        # ----------------------------------------------------------------------
        cand_input = inp.candidate_input
        if isinstance(cand_input, dict):
            cand_input_obj = CandidateIdentityInput(**cand_input)
        else:
            cand_input_obj = cand_input

        # Ensure current document_id is excluded from matching candidate with itself
        exclude_doc_id = inp.document_id or cand_input_obj.document_id

        identity_result = await self.identity_service.match_identity(
            cand_input_obj,
            existing_records=existing_records,
            exclude_document_id=exclude_doc_id,
        )

        zoho_candidate_id = (
            cand_input_obj.zoho_candidate_id
            or (identity_result.normalized_identity.get("zoho_candidate_id") if identity_result else None)
        )

        # Ambiguous identity check
        if identity_result.status == CandidateIdentityStatus.REVIEW_REQUIRED:
            return RepeatApplicationResult(
                status=RepeatApplicationStatus.IDENTITY_REVIEW_REQUIRED,
                is_repeat=False,
                candidate_id=identity_result.matched_candidate_id,
                zoho_candidate_id=str(zoho_candidate_id) if zoho_candidate_id else None,
                current_job_opening_id=current_job_id,
                current_project_id=current_proj_id,
                total_previous_applications=0,
                previous_applications=[],
                identity_match_result=identity_result,
                reasons=[
                    "Candidate identity is ambiguous. Manual identity review is required before "
                    "repeat application status can be determined."
                ] + identity_result.reasons,
            )

        # New candidate check: candidate has never appeared in ATS before
        if identity_result.status == CandidateIdentityStatus.NEW_CANDIDATE:
            return RepeatApplicationResult(
                status=RepeatApplicationStatus.FIRST_APPLICATION,
                is_repeat=False,
                candidate_id=None,
                zoho_candidate_id=str(zoho_candidate_id) if zoho_candidate_id else None,
                current_job_opening_id=current_job_id,
                current_project_id=current_proj_id,
                total_previous_applications=0,
                previous_applications=[],
                identity_match_result=identity_result,
                reasons=["Candidate is newly identified with no previous application history in the ATS."],
            )

        # ----------------------------------------------------------------------
        # Rule 3 & 4: Search application history & avoid false positives
        # ----------------------------------------------------------------------
        resolved_candidate_id = identity_result.matched_candidate_id

        history = await self._fetch_application_history(
            candidate_id=resolved_candidate_id,
            zoho_candidate_id=str(zoho_candidate_id) if zoho_candidate_id else None,
            normalized_email=identity_result.normalized_identity.get("email"),
            normalized_phone=identity_result.normalized_identity.get("phone"),
            current_job_opening_id=current_job_id,
            current_project_id=current_proj_id,
            exclude_document_id=str(exclude_doc_id) if exclude_doc_id else None,
            existing_applications=existing_applications,
            existing_records=existing_records,
            is_new_application_submission=inp.is_new_application_submission,
        )

        # Separate previous applications into same job vs different jobs
        same_job_apps = [a for a in history if a.is_same_job]
        diff_job_apps = [a for a in history if not a.is_same_job]
        total_prev = len(history)

        # Case 1: Applications exist for multiple distinct openings
        if (len(diff_job_apps) >= 2) or (len(diff_job_apps) >= 1 and len(same_job_apps) >= 1):
            distinct_jobs = {
                a.job_opening_id or str(a.project_id)
                for a in history
                if a.job_opening_id or a.project_id
            }
            return RepeatApplicationResult(
                status=RepeatApplicationStatus.MULTIPLE_PREVIOUS_APPLICATIONS,
                is_repeat=True,
                candidate_id=resolved_candidate_id,
                zoho_candidate_id=str(zoho_candidate_id) if zoho_candidate_id else None,
                current_job_opening_id=current_job_id,
                current_project_id=current_proj_id,
                total_previous_applications=total_prev,
                previous_applications=history,
                identity_match_result=identity_result,
                reasons=[
                    f"Candidate has applied to {len(distinct_jobs)} distinct previous job openings in the ATS."
                ],
            )

        # Case 2: Exactly one previous application for a different job opening
        if len(diff_job_apps) == 1 and len(same_job_apps) == 0:
            prev_job = diff_job_apps[0].job_opening_id or str(diff_job_apps[0].project_id)
            return RepeatApplicationResult(
                status=RepeatApplicationStatus.REPEAT_APPLICATION_DIFFERENT_JOB,
                is_repeat=True,
                candidate_id=resolved_candidate_id,
                zoho_candidate_id=str(zoho_candidate_id) if zoho_candidate_id else None,
                current_job_opening_id=current_job_id,
                current_project_id=current_proj_id,
                total_previous_applications=total_prev,
                previous_applications=history,
                identity_match_result=identity_result,
                reasons=[
                    f"Candidate previously applied to another job opening: {prev_job}."
                ],
            )

        # Case 3: Previous application for the same job opening
        if len(same_job_apps) >= 1 and len(diff_job_apps) == 0:
            return RepeatApplicationResult(
                status=RepeatApplicationStatus.REPEAT_APPLICATION_SAME_JOB,
                is_repeat=True,
                candidate_id=resolved_candidate_id,
                zoho_candidate_id=str(zoho_candidate_id) if zoho_candidate_id else None,
                current_job_opening_id=current_job_id,
                current_project_id=current_proj_id,
                total_previous_applications=total_prev,
                previous_applications=history,
                identity_match_result=identity_result,
                reasons=[
                    f"Candidate previously applied to this same job opening ({current_job_id or current_proj_id})."
                ],
            )

        # Case 4: No previous applications found
        return RepeatApplicationResult(
            status=RepeatApplicationStatus.FIRST_APPLICATION,
            is_repeat=False,
            candidate_id=resolved_candidate_id,
            zoho_candidate_id=str(zoho_candidate_id) if zoho_candidate_id else None,
            current_job_opening_id=current_job_id,
            current_project_id=current_proj_id,
            total_previous_applications=0,
            previous_applications=[],
            identity_match_result=identity_result,
            reasons=["No previous applications found for this candidate in the ATS."],
        )

    # ==========================================================================
    # History Retrieval & Rule 4 Deduplication
    # ==========================================================================

    async def _fetch_application_history(
        self,
        *,
        candidate_id: str | None,
        zoho_candidate_id: str | None,
        normalized_email: str | None,
        normalized_phone: str | None,
        current_job_opening_id: str | None,
        current_project_id: str | None,
        exclude_document_id: str | None,
        existing_applications: list[ApplicationHistoryItem] | None,
        existing_records: list[CandidateIdentityRecord] | None,
        is_new_application_submission: bool,
    ) -> list[ApplicationHistoryItem]:
        """Fetch, group, and deduplicate previous applications for the candidate."""
        # 1. If caller supplied explicit pre-formed applications (e.g. unit tests):
        if existing_applications is not None:
            results: list[ApplicationHistoryItem] = []
            for app in existing_applications:
                # Mark same job vs different job
                is_same = self._is_same_job(
                    app_job_id=app.job_opening_id,
                    app_proj_id=str(app.project_id) if app.project_id else None,
                    curr_job_id=current_job_opening_id,
                    curr_proj_id=current_project_id,
                )
                app_copy = app.model_copy(update={"is_same_job": is_same})
                results.append(app_copy)
            return results

        # 2. If caller supplied candidate records in-memory:
        if existing_records is not None:
            return self._group_records_into_applications(
                records=existing_records,
                candidate_id=candidate_id,
                zoho_candidate_id=zoho_candidate_id,
                normalized_email=normalized_email,
                normalized_phone=normalized_phone,
                current_job_opening_id=current_job_opening_id,
                current_project_id=current_project_id,
                exclude_document_id=exclude_document_id,
                is_new_application_submission=is_new_application_submission,
            )

        # 3. Query PostgreSQL via SQLAlchemy
        if self.session is None:
            return []

        # Find all documents belonging to this candidate
        filters = []
        if candidate_id:
            try:
                filters.append(DocumentModel.id == UUID(candidate_id))
            except ValueError:
                pass
        if zoho_candidate_id:
            filters.append(DocumentModel.metadata_json["zoho_candidate_id"].as_string() == zoho_candidate_id)
        if normalized_email:
            filters.append(DocumentModel.metadata_json["email"].as_string() == normalized_email)
            filters.append(NormalizedResumeModel.email == normalized_email)
            filters.append(ExtractedResumeModel.email == normalized_email)
        if normalized_phone:
            filters.append(DocumentModel.metadata_json["phone"].as_string() == normalized_phone)
            filters.append(NormalizedResumeModel.phone == normalized_phone)
            filters.append(ExtractedResumeModel.phone == normalized_phone)

        if not filters:
            return []

        stmt = (
            select(DocumentModel)
            .outerjoin(NormalizedResumeModel, NormalizedResumeModel.document_id == DocumentModel.id)
            .outerjoin(ExtractedResumeModel, ExtractedResumeModel.document_id == DocumentModel.id)
            .where(
                DocumentModel.document_type == DocumentTypeEnum.RESUME,
                DocumentModel.deleted_at.is_(None),
                or_(*filters),
            )
        )
        if exclude_document_id:
            try:
                stmt = stmt.where(DocumentModel.id != UUID(exclude_document_id))
            except ValueError:
                pass

        docs = (await self.session.scalars(stmt)).all()

        # Group docs into distinct applications
        return self._group_documents_into_applications(
            docs=docs,
            current_job_opening_id=current_job_opening_id,
            current_project_id=current_project_id,
            is_new_application_submission=is_new_application_submission,
        )

    def _is_same_job(
        self,
        *,
        app_job_id: str | None,
        app_proj_id: str | None,
        curr_job_id: str | None,
        curr_proj_id: str | None,
    ) -> bool:
        """Deterministic check for whether an application refers to the same job opening."""
        if curr_job_id and app_job_id and curr_job_id == app_job_id:
            return True
        if curr_proj_id and app_proj_id and curr_proj_id == app_proj_id:
            return True
        return False

    def _group_records_into_applications(
        self,
        *,
        records: list[CandidateIdentityRecord],
        candidate_id: str | None,
        zoho_candidate_id: str | None,
        normalized_email: str | None,
        normalized_phone: str | None,
        current_job_opening_id: str | None,
        current_project_id: str | None,
        exclude_document_id: str | None,
        is_new_application_submission: bool,
    ) -> list[ApplicationHistoryItem]:
        """Group candidate identity records into deduplicated applications."""
        # Map: job_key -> ApplicationHistoryItem
        grouped: dict[str, ApplicationHistoryItem] = {}

        for rec in records:
            doc_id_str = str(rec.document_id)
            if exclude_document_id and doc_id_str == exclude_document_id:
                continue

            # Check if this record belongs to the resolved candidate
            is_candidate_match = False
            if candidate_id and doc_id_str == candidate_id:
                is_candidate_match = True
            elif zoho_candidate_id and rec.zoho_candidate_id and str(rec.zoho_candidate_id).strip() == zoho_candidate_id:
                is_candidate_match = True
            elif normalized_email and rec.email:
                c_email, _ = normalize_email_address(rec.email)
                if c_email and c_email == normalized_email:
                    is_candidate_match = True
            elif normalized_phone and rec.phone:
                c_phone, _ = normalize_phone_number(rec.phone)
                if c_phone and c_phone == normalized_phone:
                    is_candidate_match = True

            if not is_candidate_match:
                continue

            # Determine job opening for this record
            job_id = getattr(rec, "zoho_job_opening_id", None) or getattr(rec, "job_opening_id", None)
            proj_id = getattr(rec, "project_id", None)
            if not job_id and not proj_id:
                # A document without an associated job opening or project is not a job application
                continue
            job_key = str(job_id or proj_id)

            is_same = self._is_same_job(
                app_job_id=str(job_id) if job_id else None,
                app_proj_id=str(proj_id) if proj_id else None,
                curr_job_id=current_job_opening_id,
                curr_proj_id=current_project_id,
            )

            # Rule 4: If this record is in the same job opening, and this upload is NOT a
            # new separate application submission, it represents the current application
            # (or additional attachment / re-upload), not a prior repeat application event.
            if is_same and not is_new_application_submission:
                continue

            if job_key not in grouped:
                grouped[job_key] = ApplicationHistoryItem(
                    job_opening_id=str(job_id) if job_id else None,
                    project_id=proj_id,
                    job_title=getattr(rec, "job_title", None),
                    document_ids=[rec.document_id],
                    is_same_job=is_same,
                )
            else:
                # Group multiple attachments under the existing application (Rule 4)
                if rec.document_id not in grouped[job_key].document_ids:
                    grouped[job_key].document_ids.append(rec.document_id)

        return list(grouped.values())

    def _group_documents_into_applications(
        self,
        *,
        docs: list[DocumentModel],
        current_job_opening_id: str | None,
        current_project_id: str | None,
        is_new_application_submission: bool,
    ) -> list[ApplicationHistoryItem]:
        """Group SQLAlchemy DocumentModel records into deduplicated applications."""
        grouped: dict[str, ApplicationHistoryItem] = {}

        for doc in docs:
            meta = doc.metadata_json or {}
            job_id = meta.get("zoho_job_opening_id") or meta.get("job_opening_id")
            proj_id = str(doc.project_id) if doc.project_id else None
            if not job_id and not proj_id:
                continue
            job_key = str(job_id or proj_id)

            is_same = self._is_same_job(
                app_job_id=str(job_id) if job_id else None,
                app_proj_id=proj_id,
                curr_job_id=current_job_opening_id,
                curr_proj_id=current_project_id,
            )

            # Rule 4: Same job without explicit new application submission is the same application
            if is_same and not is_new_application_submission:
                continue

            if job_key not in grouped:
                grouped[job_key] = ApplicationHistoryItem(
                    job_opening_id=str(job_id) if job_id else None,
                    project_id=doc.project_id,
                    job_title=meta.get("job_title") or meta.get("zoho_job_opening_title"),
                    document_ids=[doc.id],
                    applied_at=doc.created_at,
                    is_same_job=is_same,
                )
            else:
                if doc.id not in grouped[job_key].document_ids:
                    grouped[job_key].document_ids.append(doc.id)

        return list(grouped.values())
