from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.exceptions import AppException, InternalServerException
from app.models.document import DocumentModel, DocumentTypeEnum
from app.models.extracted_info import ExtractedResumeModel
from app.models.normalized_info import NormalizedResumeModel
from app.models.project import ProjectModel
from app.schemas.candidate_identity import (
    CandidateIdentityInput,
    CandidateIdentityRecord,
    CandidateIdentityStatus,
)
from app.schemas.candidate_verification import (
    BatchVerificationStatus,
    BatchVerificationSummary,
    CandidateManualReviewRead,
    CandidateManualReviewRequest,
    CandidateVerificationItemResult,
    CandidateVerificationStatus,
    ManualReviewDecision,
    is_document_verified,
)
from app.schemas.repeat_application import (
    RepeatApplicationInput,
    RepeatApplicationStatus,
)
from app.services.candidate_identity_service import CandidateIdentityService
from app.services.document_service import (
    DocumentBelongsToAnotherProjectException,
    DocumentNotFoundException,
)
from app.services.pipeline.identity_rules import (
    normalize_candidate_identity,
    normalize_email_address,
    normalize_phone_number,
)
from app.services.project_service import ProjectNotFoundException
from app.services.repeat_application_service import RepeatApplicationService

logger = structlog.get_logger(__name__)


class ReviewNotRequiredException(AppException):
    status_code = 400
    error_code = "REVIEW_NOT_REQUIRED"
    default_message = "Document does not require manual identity review."


class CandidateVerificationService:
    """Phase 4 Batch Candidate Verification Engine.

    Verifies all candidates associated with a job opening by orchestrating:
    1. Phase 1 Deterministic Identity Data Preparation
    2. Phase 2 Candidate Identity Matching
    3. Phase 3 Repeat Application Detection

    Groups duplicate attachments, handles individual failures, updates progress,
    supports safe retries, and persists results.
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        identity_service: CandidateIdentityService | None = None,
        repeat_service: RepeatApplicationService | None = None,
    ) -> None:
        self.session = session
        self.identity_service = identity_service or CandidateIdentityService(session)
        self.repeat_service = repeat_service or RepeatApplicationService(
            session=session, identity_service=self.identity_service
        )

    async def verify_job_opening_candidates(
        self,
        project_id_or_job_id: str | UUID,
        *,
        force_reverify: bool = False,
        in_memory_project: dict[str, Any] | None = None,
        in_memory_records: list[CandidateIdentityRecord | dict[str, Any]] | None = None,
        in_memory_ats_records: list[CandidateIdentityRecord] | None = None,
    ) -> BatchVerificationSummary:
        """Execute batch verification for all candidates associated with a job opening."""
        batch_id = str(uuid4())
        started_at = datetime.now(UTC)

        # ----------------------------------------------------------------------
        # Step 1: Resolve the job opening to an internal Project / Job Opening
        # ----------------------------------------------------------------------
        project, resolved_proj_id, resolved_job_id, job_title = await self._resolve_job_opening(
            project_id_or_job_id, in_memory_project=in_memory_project
        )

        if not resolved_proj_id and not resolved_job_id:
            if in_memory_records is not None:
                resolved_proj_id = str(project_id_or_job_id)
                resolved_job_id = str(project_id_or_job_id)
            else:
                return BatchVerificationSummary(
                    batch_id=batch_id,
                    job_opening_id=str(project_id_or_job_id),
                    status=BatchVerificationStatus.FAILED,
                    error_message=f"Job opening or project '{project_id_or_job_id}' not found.",
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )

        # ----------------------------------------------------------------------
        # Step 2 & 3: Collect and group eligible candidate/resume records
        # ----------------------------------------------------------------------
        candidate_groups = await self._collect_and_group_candidates(
            project=project,
            resolved_proj_id=resolved_proj_id,
            resolved_job_id=resolved_job_id,
            in_memory_records=in_memory_records,
        )

        total_candidates = len(candidate_groups)
        if total_candidates == 0:
            summary = BatchVerificationSummary(
                batch_id=batch_id,
                project_id=resolved_proj_id,
                job_opening_id=resolved_job_id,
                status=BatchVerificationStatus.COMPLETED,
                total_candidates=0,
                processed_candidates=0,
                progress_percentage=100.0,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                results=[],
            )
            await self._persist_project_summary(project, summary)
            return summary

        # ----------------------------------------------------------------------
        # Step 4 & 5: Process each candidate independently
        # ----------------------------------------------------------------------
        results: list[CandidateVerificationItemResult] = []
        verified_count = 0
        review_count = 0
        failed_count = 0

        for candidate_key, group in candidate_groups.items():
            try:
                # Check safe retry: if not force_reverify, reuse previously verified result if valid
                if not force_reverify and group.get("previous_verification"):
                    prev = group["previous_verification"]
                    if prev.get("verification_status") == CandidateVerificationStatus.VERIFIED.value:
                        item_result = CandidateVerificationItemResult(**prev)
                        results.append(item_result)
                        verified_count += 1
                        continue

                # Run verification pipeline for this candidate
                item_result = await self._verify_single_candidate(
                    group=group,
                    current_job_id=resolved_job_id,
                    current_proj_id=resolved_proj_id,
                    job_title=job_title,
                    in_memory_ats_records=in_memory_ats_records,
                )

                if item_result.verification_status == CandidateVerificationStatus.VERIFIED:
                    verified_count += 1
                elif item_result.verification_status == CandidateVerificationStatus.REVIEW_REQUIRED:
                    review_count += 1
                else:
                    failed_count += 1

                results.append(item_result)

                # Persist on individual document records in the group
                await self._persist_candidate_result(group, item_result)

            except Exception as exc:
                logger.error(
                    "candidate_verification_failed",
                    candidate_key=candidate_key,
                    error=str(exc),
                )
                failed_count += 1
                failed_result = CandidateVerificationItemResult(
                    candidate_identifier=candidate_key,
                    document_ids=group.get("document_ids", []),
                    candidate_name=group.get("candidate_name"),
                    email=group.get("email"),
                    phone=group.get("phone"),
                    zoho_candidate_id=group.get("zoho_candidate_id"),
                    verification_status=CandidateVerificationStatus.FAILED,
                    error_message=str(exc),
                    verified_at=datetime.now(UTC),
                )
                results.append(failed_result)
                await self._persist_candidate_result(group, failed_result)

        # ----------------------------------------------------------------------
        # Step 6: Determine aggregate status and persist summary
        # ----------------------------------------------------------------------
        completed_at = datetime.now(UTC)
        processed_candidates = len(results)
        progress_percentage = 100.0 if total_candidates > 0 else 0.0

        if failed_count == total_candidates and total_candidates > 0:
            final_status = BatchVerificationStatus.FAILED
        elif failed_count > 0 or review_count > 0:
            final_status = BatchVerificationStatus.PARTIAL_SUCCESS
        else:
            final_status = BatchVerificationStatus.COMPLETED

        summary = BatchVerificationSummary(
            batch_id=batch_id,
            job_opening_id=resolved_job_id,
            project_id=resolved_proj_id,
            status=final_status,
            total_candidates=total_candidates,
            processed_candidates=processed_candidates,
            verified_candidates=verified_count,
            review_required_candidates=review_count,
            failed_candidates=failed_count,
            progress_percentage=progress_percentage,
            started_at=started_at,
            completed_at=completed_at,
            results=results,
        )

        await self._persist_project_summary(project, summary)
        return summary

    async def get_verification_status(
        self,
        project_id_or_job_id: str | UUID,
        *,
        in_memory_project: dict[str, Any] | None = None,
    ) -> BatchVerificationSummary:
        """Retrieve the latest persisted verification status for a job opening."""
        project, resolved_proj_id, resolved_job_id, _ = await self._resolve_job_opening(
            project_id_or_job_id, in_memory_project=in_memory_project
        )

        meta = (project.metadata_json or {}) if project else (in_memory_project or {})
        verification_data = meta.get("candidate_verification")

        if verification_data:
            return BatchVerificationSummary(**verification_data)

        return BatchVerificationSummary(
            batch_id=str(uuid4()),
            job_opening_id=resolved_job_id or str(project_id_or_job_id),
            project_id=resolved_proj_id,
            status=BatchVerificationStatus.NOT_STARTED,
            total_candidates=0,
            processed_candidates=0,
            progress_percentage=0.0,
            results=[],
        )

    async def retry_failed_candidates(
        self,
        project_id_or_job_id: str | UUID,
        *,
        in_memory_project: dict[str, Any] | None = None,
        in_memory_records: list[CandidateIdentityRecord | dict[str, Any]] | None = None,
        in_memory_ats_records: list[CandidateIdentityRecord] | None = None,
    ) -> BatchVerificationSummary:
        """Safely retry only failed or unverified candidates without re-verifying successful ones."""
        return await self.verify_job_opening_candidates(
            project_id_or_job_id=project_id_or_job_id,
            force_reverify=False,
            in_memory_project=in_memory_project,
            in_memory_records=in_memory_records,
            in_memory_ats_records=in_memory_ats_records,
        )

    async def review_candidate_document(
        self,
        project_id: UUID | str,
        document_id: UUID | str,
        payload: CandidateManualReviewRequest,
        *,
        reviewer_id: str | None = None,
        in_memory_project: dict[str, Any] | None = None,
        in_memory_documents: list[dict[str, Any]] | None = None,
    ) -> CandidateManualReviewRead:
        """Manually approve or reject a candidate resume whose identity requires review.

        Validates project/document ownership, ensures the document currently requires review,
        and persists the decision with audit history in DocumentModel.metadata_json['verification']
        and updates the aggregate ProjectModel.metadata_json['candidate_verification'].
        """
        proj_id_str = str(project_id).strip()
        doc_id_str = str(document_id).strip()

        # ------------------------------------------------------------------
        # 1. In-memory mode (for isolated testing without active DB session)
        # ------------------------------------------------------------------
        if in_memory_project is not None or in_memory_documents is not None:
            if in_memory_project is None or str(in_memory_project.get("id") or in_memory_project.get("project_id")) != proj_id_str:
                raise ProjectNotFoundException(f"Project '{project_id}' not found.")

            target_doc = None
            for d in (in_memory_documents or []):
                if str(d.get("id") or d.get("document_id")) == doc_id_str:
                    target_doc = d
                    break

            if target_doc is None:
                raise DocumentNotFoundException(f"Document '{document_id}' not found.")

            doc_proj_id = str(target_doc.get("project_id") or "")
            if doc_proj_id != proj_id_str:
                raise DocumentBelongsToAnotherProjectException(
                    f"Document '{document_id}' does not belong to project '{project_id}'."
                )

            doc_type = target_doc.get("document_type")
            if doc_type and str(doc_type).upper() not in ("RESUME", "DOCUMENTTYPEENUM.RESUME"):
                raise ReviewNotRequiredException(
                    f"Document '{document_id}' is not a candidate resume."
                )

            meta = dict(target_doc.get("metadata_json") or {})
            ver_data = meta.get("verification")
            if not ver_data or not isinstance(ver_data, dict):
                raise ReviewNotRequiredException(
                    f"Document '{document_id}' has not undergone candidate identity verification."
                )

            curr_status = ver_data.get("verification_status")
            if curr_status != CandidateVerificationStatus.REVIEW_REQUIRED.value:
                raise ReviewNotRequiredException(
                    f"Document '{document_id}' does not require review (current verification status: '{curr_status}'). "
                    f"Manual review is only permitted for documents in 'REVIEW_REQUIRED' status."
                )

            reviewed_at = datetime.now(UTC)
            decision = payload.decision
            new_status = (
                CandidateVerificationStatus.VERIFIED
                if decision == ManualReviewDecision.APPROVE
                else CandidateVerificationStatus.REJECTED
            )
            note = payload.review_note.strip() if payload.review_note and payload.review_note.strip() else None

            updated_ver = dict(ver_data)
            updated_ver["verification_status"] = new_status.value
            updated_ver["review_decision"] = decision.value
            updated_ver["review_note"] = note
            updated_ver["reviewed_at"] = reviewed_at.isoformat()
            updated_ver["reviewed_by"] = reviewer_id

            existing_reasons = list(updated_ver.get("reasons") or [])
            audit_reason = f"Manual identity review: {decision.value}"
            if note:
                audit_reason += f" - {note}"
            existing_reasons.append(audit_reason)
            updated_ver["reasons"] = existing_reasons

            meta["verification"] = updated_ver
            target_doc["metadata_json"] = meta

            # Update project summary if present in in_memory_project
            if in_memory_project and "candidate_verification" in in_memory_project:
                summary_data = in_memory_project["candidate_verification"]
                if isinstance(summary_data, dict) and "results" in summary_data:
                    for r in summary_data["results"]:
                        r_doc_ids = [str(did) for did in r.get("document_ids", [])]
                        if doc_id_str in r_doc_ids and len(r_doc_ids) <= 1:
                            r["verification_status"] = new_status.value
                            r["review_decision"] = decision.value
                            r["review_note"] = note
                            r["reviewed_at"] = reviewed_at.isoformat()
                            r["reviewed_by"] = reviewer_id
                            r["reasons"] = list(r.get("reasons") or []) + [audit_reason]
                            break

            item_result = CandidateVerificationItemResult(**updated_ver)
            return CandidateManualReviewRead(
                document_id=doc_id_str,
                project_id=proj_id_str,
                decision=decision,
                verification_status=new_status,
                review_note=note,
                reviewed_at=reviewed_at,
                reviewed_by=reviewer_id,
                candidate_result=item_result,
            )

        # ------------------------------------------------------------------
        # 2. Database mode (active SQLAlchemy async session)
        # ------------------------------------------------------------------
        if self.session is None:
            raise InternalServerException("Database session required for candidate review persistence.")

        try:
            proj_uuid = UUID(proj_id_str)
        except (ValueError, AttributeError):
            raise ProjectNotFoundException(f"Project '{project_id}' not found.")

        try:
            doc_uuid = UUID(doc_id_str)
        except (ValueError, AttributeError):
            raise DocumentNotFoundException(f"Document '{document_id}' not found.")

        project = await self.session.get(ProjectModel, proj_uuid)
        if not project or project.deleted_at is not None:
            raise ProjectNotFoundException(f"Project '{project_id}' not found.")

        document = await self.session.get(DocumentModel, doc_uuid)
        if not document or document.deleted_at is not None:
            raise DocumentNotFoundException(f"Document '{document_id}' not found.")

        if document.project_id != project.id:
            raise DocumentBelongsToAnotherProjectException(
                f"Document '{document_id}' does not belong to project '{project_id}'."
            )

        if document.document_type != DocumentTypeEnum.RESUME:
            raise ReviewNotRequiredException(
                f"Document '{document_id}' is not a resume (document_type is '{document.document_type}')."
            )

        doc_meta = dict(document.metadata_json or {})
        ver_data = doc_meta.get("verification")
        if not ver_data or not isinstance(ver_data, dict):
            raise ReviewNotRequiredException(
                f"Document '{document_id}' has not undergone candidate identity verification."
            )

        curr_status = ver_data.get("verification_status")
        if curr_status != CandidateVerificationStatus.REVIEW_REQUIRED.value:
            raise ReviewNotRequiredException(
                f"Document '{document_id}' does not require review (current verification status: '{curr_status}'). "
                f"Manual review is only permitted for documents in 'REVIEW_REQUIRED' status."
            )

        reviewed_at = datetime.now(UTC)
        decision = payload.decision
        new_status = (
            CandidateVerificationStatus.VERIFIED
            if decision == ManualReviewDecision.APPROVE
            else CandidateVerificationStatus.REJECTED
        )
        note = payload.review_note.strip() if payload.review_note and payload.review_note.strip() else None

        updated_ver = dict(ver_data)
        updated_ver["verification_status"] = new_status.value
        updated_ver["review_decision"] = decision.value
        updated_ver["review_note"] = note
        updated_ver["reviewed_at"] = reviewed_at.isoformat()
        updated_ver["reviewed_by"] = reviewer_id

        existing_reasons = list(updated_ver.get("reasons") or [])
        audit_reason = f"Manual identity review: {decision.value}"
        if note:
            audit_reason += f" - {note}"
        existing_reasons.append(audit_reason)
        updated_ver["reasons"] = existing_reasons

        # Persist on individual DocumentModel
        document.metadata_json = {
            **doc_meta,
            "verification": updated_ver,
        }

        # Update ProjectModel.metadata_json['candidate_verification'] summary
        proj_meta = dict(project.metadata_json or {})
        summary_dict = proj_meta.get("candidate_verification")
        if summary_dict and isinstance(summary_dict, dict) and "results" in summary_dict:
            results_list = list(summary_dict.get("results") or [])
            for idx, r in enumerate(results_list):
                r_doc_ids = [str(did) for did in r.get("document_ids", [])]
                if str(doc_uuid) in r_doc_ids:
                    if len(r_doc_ids) <= 1:
                        # Isolated candidate unit with single document
                        r["verification_status"] = new_status.value
                        r["review_decision"] = decision.value
                        r["review_note"] = note
                        r["reviewed_at"] = reviewed_at.isoformat()
                        r["reviewed_by"] = reviewer_id
                        r["reasons"] = list(r.get("reasons") or []) + [audit_reason]
                    else:
                        # Candidate with multiple attachments: check other documents' statuses
                        other_docs_stmt = select(DocumentModel).where(
                            DocumentModel.id.in_([UUID(d) for d in r_doc_ids if d != str(doc_uuid)]),
                            DocumentModel.deleted_at.is_(None),
                        )
                        other_docs = (await self.session.scalars(other_docs_stmt)).all()
                        other_statuses = [
                            ((od.metadata_json or {}).get("verification") or {}).get("verification_status")
                            for od in other_docs
                        ]
                        if decision == ManualReviewDecision.APPROVE and all(s == CandidateVerificationStatus.VERIFIED.value for s in other_statuses):
                            r["verification_status"] = CandidateVerificationStatus.VERIFIED.value
                        r["reasons"] = list(r.get("reasons") or []) + [
                            f"Document {doc_uuid} manual review: {decision.value}"
                        ]
                    results_list[idx] = r
                    break

            summary_dict["results"] = results_list
            summary_dict["verified_candidates"] = sum(
                1 for r in results_list if r.get("verification_status") == CandidateVerificationStatus.VERIFIED.value
            )
            summary_dict["review_required_candidates"] = sum(
                1 for r in results_list if r.get("verification_status") == CandidateVerificationStatus.REVIEW_REQUIRED.value
            )
            summary_dict["failed_candidates"] = sum(
                1 for r in results_list if r.get("verification_status") in (
                    CandidateVerificationStatus.FAILED.value,
                    CandidateVerificationStatus.REJECTED.value,
                )
            )
            proj_meta["candidate_verification"] = summary_dict
            project.metadata_json = proj_meta

        await self.session.commit()
        await self.session.refresh(document)
        await self.session.refresh(project)

        item_result = CandidateVerificationItemResult(**updated_ver)
        return CandidateManualReviewRead(
            document_id=doc_uuid,
            project_id=project.id,
            decision=decision,
            verification_status=new_status,
            review_note=note,
            reviewed_at=reviewed_at,
            reviewed_by=reviewer_id,
            candidate_result=item_result,
        )

    # ==========================================================================
    # Verification Execution Helpers
    # ==========================================================================

    async def _verify_single_candidate(
        self,
        *,
        group: dict[str, Any],
        current_job_id: str | None,
        current_proj_id: str | None,
        job_title: str | None,
        in_memory_ats_records: list[CandidateIdentityRecord] | None,
    ) -> CandidateVerificationItemResult:
        """Execute Phase 1, Phase 2, and Phase 3 verification for one candidate unit."""
        doc_ids = group.get("document_ids", [])
        primary_doc_id = doc_ids[0] if doc_ids else None

        # Phase 1: Identity normalization
        norm_identity = normalize_candidate_identity(
            candidate_name=group.get("candidate_name"),
            email=group.get("email"),
            phone=group.get("phone"),
        )

        # Phase 2: Candidate identity matching
        cand_input = CandidateIdentityInput(
            document_id=primary_doc_id,
            candidate_name=norm_identity.get("candidate_name"),
            email=norm_identity.get("email"),
            phone=norm_identity.get("phone"),
            zoho_candidate_id=group.get("zoho_candidate_id"),
            zoho_attachment_id=group.get("zoho_attachment_id"),
        )

        identity_match = await self.identity_service.match_identity(
            cand_input,
            existing_records=in_memory_ats_records,
            exclude_document_id=primary_doc_id,
        )

        # Phase 3: Repeat application detection
        repeat_input = RepeatApplicationInput(
            candidate_input=cand_input,
            job_opening_id=current_job_id,
            project_id=current_proj_id,
            document_id=primary_doc_id,
            job_title=job_title,
            is_new_application_submission=False,
        )

        repeat_match = await self.repeat_service.detect_repeat_application(
            repeat_input,
            existing_records=in_memory_ats_records,
        )

        # Synthesize status
        is_review = (
            identity_match.status == CandidateIdentityStatus.REVIEW_REQUIRED
            or repeat_match.status == RepeatApplicationStatus.IDENTITY_REVIEW_REQUIRED
        )

        verification_status = (
            CandidateVerificationStatus.REVIEW_REQUIRED
            if is_review
            else CandidateVerificationStatus.VERIFIED
        )

        # Aggregate reasons and conflicts
        all_reasons = identity_match.reasons + repeat_match.reasons
        all_conflicts = identity_match.conflicts

        return CandidateVerificationItemResult(
            candidate_identifier=group["candidate_key"],
            document_ids=doc_ids,
            candidate_name=norm_identity.get("candidate_name") or group.get("candidate_name"),
            email=norm_identity.get("email") or group.get("email"),
            phone=norm_identity.get("phone") or group.get("phone"),
            zoho_candidate_id=group.get("zoho_candidate_id"),
            verification_status=verification_status,
            identity_status=identity_match.status,
            repeat_application_status=repeat_match.status,
            is_repeat_applicant=repeat_match.is_repeat,
            confidence=identity_match.confidence,
            reasons=all_reasons,
            conflicts=all_conflicts,
            previous_applications=repeat_match.previous_applications,
            verified_at=datetime.now(UTC),
            error_message=None,
        )

    # ==========================================================================
    # Grouping & Resolution Helpers
    # ==========================================================================

    async def _resolve_job_opening(
        self,
        project_id_or_job_id: str | UUID,
        *,
        in_memory_project: dict[str, Any] | None = None,
    ) -> tuple[ProjectModel | None, str | None, str | None, str | None]:
        """Resolve project_id_or_job_id to ProjectModel and IDs."""
        id_str = str(project_id_or_job_id).strip()

        if in_memory_project is not None:
            proj_id = in_memory_project.get("id") or in_memory_project.get("project_id")
            job_id = (
                in_memory_project.get("zoho_job_opening_id")
                or in_memory_project.get("job_opening_id")
                or id_str
            )
            title = in_memory_project.get("title") or in_memory_project.get("target_role")
            return None, str(proj_id) if proj_id else None, str(job_id) if job_id else None, title

        if self.session is None:
            return None, None, None, None

        # Check by Project UUID
        try:
            uuid_obj = UUID(id_str)
            stmt = select(ProjectModel).where(
                ProjectModel.id == uuid_obj,
                ProjectModel.deleted_at.is_(None),
            )
            project = (await self.session.scalars(stmt)).first()
            if project:
                meta = project.metadata_json or {}
                job_id = meta.get("zoho_job_opening_id") or meta.get("job_opening_id")
                return project, str(project.id), str(job_id) if job_id else None, project.title
        except ValueError:
            pass

        # Check by Zoho Job Opening ID in ProjectModel.metadata_json
        stmt = select(ProjectModel).where(
            ProjectModel.deleted_at.is_(None),
            ProjectModel.metadata_json["zoho_job_opening_id"].as_string() == id_str,
        )
        project = (await self.session.scalars(stmt)).first()
        if project:
            return project, str(project.id), id_str, project.title

        return None, None, None, None

    async def _collect_and_group_candidates(
        self,
        *,
        project: ProjectModel | None,
        resolved_proj_id: str | None,
        resolved_job_id: str | None,
        in_memory_records: list[CandidateIdentityRecord | dict[str, Any]] | None,
    ) -> dict[str, dict[str, Any]]:
        """Collect and group candidate records by identity to avoid duplicate tasks."""
        candidate_groups: dict[str, dict[str, Any]] = {}

        # 1. In-memory mode
        if in_memory_records is not None:
            for item in in_memory_records:
                if isinstance(item, dict):
                    doc_id = item.get("document_id") or str(uuid4())
                    name = item.get("candidate_name")
                    email = item.get("email")
                    phone = item.get("phone")
                    zid = item.get("zoho_candidate_id")
                    att_id = item.get("zoho_attachment_id")
                    prev_ver = item.get("verification")
                else:
                    doc_id = item.document_id
                    name = item.candidate_name
                    email = item.email
                    phone = item.phone
                    zid = item.zoho_candidate_id
                    att_id = item.zoho_attachment_id
                    prev_ver = getattr(item, "verification", None)

                key = self._get_candidate_group_key(zid=zid, email=email, phone=phone, fallback_id=str(doc_id))

                if key not in candidate_groups:
                    candidate_groups[key] = {
                        "candidate_key": key,
                        "document_ids": [doc_id],
                        "candidate_name": name,
                        "email": email,
                        "phone": phone,
                        "zoho_candidate_id": zid,
                        "zoho_attachment_id": att_id,
                        "previous_verification": prev_ver,
                        "documents": [],
                    }
                else:
                    if doc_id not in candidate_groups[key]["document_ids"]:
                        candidate_groups[key]["document_ids"].append(doc_id)
                    if not candidate_groups[key]["candidate_name"] and name:
                        candidate_groups[key]["candidate_name"] = name
            return candidate_groups

        # 2. Database mode
        if self.session is None or not resolved_proj_id:
            return {}

        stmt = (
            select(DocumentModel)
            .options(
                selectinload(DocumentModel.normalized_resume),
                selectinload(DocumentModel.extracted_resume),
            )
            .where(
                DocumentModel.project_id == UUID(resolved_proj_id),
                DocumentModel.document_type == DocumentTypeEnum.RESUME,
                DocumentModel.deleted_at.is_(None),
            )
        )
        docs = (await self.session.scalars(stmt)).all()

        for doc in docs:
            meta = doc.metadata_json or {}
            zid = meta.get("zoho_candidate_id")
            att_id = meta.get("zoho_attachment_id")
            name = meta.get("candidate_name") or (doc.extracted_resume.candidate_name if doc.extracted_resume else None)
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
            prev_ver = meta.get("verification")

            key = self._get_candidate_group_key(zid=zid, email=email, phone=phone, fallback_id=str(doc.id))

            if key not in candidate_groups:
                candidate_groups[key] = {
                    "candidate_key": key,
                    "document_ids": [doc.id],
                    "candidate_name": name,
                    "email": email,
                    "phone": phone,
                    "zoho_candidate_id": zid,
                    "zoho_attachment_id": att_id,
                    "previous_verification": prev_ver,
                    "documents": [doc],
                }
            else:
                if doc.id not in candidate_groups[key]["document_ids"]:
                    candidate_groups[key]["document_ids"].append(doc.id)
                candidate_groups[key]["documents"].append(doc)
                if not candidate_groups[key]["candidate_name"] and name:
                    candidate_groups[key]["candidate_name"] = name

        return candidate_groups

    def _get_candidate_group_key(
        self,
        *,
        zid: str | None,
        email: str | None,
        phone: str | None,
        fallback_id: str,
    ) -> str:
        """Derive a stable candidate grouping key to unify multiple attachments."""
        if zid and str(zid).strip():
            return f"zoho_{str(zid).strip()}"
        if email:
            norm_e, _ = normalize_email_address(email)
            if norm_e:
                return f"email_{norm_e}"
        if phone:
            norm_p, _ = normalize_phone_number(phone)
            if norm_p:
                return f"phone_{norm_p}"
        return f"doc_{fallback_id}"

    # ==========================================================================
    # Persistence Helpers
    # ==========================================================================

    async def _persist_candidate_result(
        self, group: dict[str, Any], result: CandidateVerificationItemResult
    ) -> None:
        """Persist verification result on DocumentModel metadata_json."""
        res_dict = result.model_dump(mode="json")
        for doc in group.get("documents", []):
            doc.metadata_json = {
                **(doc.metadata_json or {}),
                "verification": res_dict,
            }

    async def _persist_project_summary(
        self, project: ProjectModel | None, summary: BatchVerificationSummary
    ) -> None:
        """Persist batch summary on ProjectModel metadata_json."""
        if project is not None:
            sum_dict = summary.model_dump(mode="json")
            project.metadata_json = {
                **(project.metadata_json or {}),
                "candidate_verification": sum_dict,
            }
            if self.session is not None:
                await self.session.commit()
