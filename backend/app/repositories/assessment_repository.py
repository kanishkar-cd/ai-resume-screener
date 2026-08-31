from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment_invitation import CandidateAssessmentModel


class AssessmentRepository:
    """Repository for candidate assessment invitations and evaluation records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_assessment(self, model: CandidateAssessmentModel) -> CandidateAssessmentModel:
        self.db.add(model)
        await self.db.flush()
        return model

    async def create_or_update_assessment(self, model: CandidateAssessmentModel) -> CandidateAssessmentModel:
        existing = await self.get_by_document_and_project(model.document_id, model.project_id)
        if existing:
            existing.requisition_ref = model.requisition_ref
            existing.drive_id = model.drive_id
            existing.external_candidate_ref = model.external_candidate_ref
            existing.idempotency_key = model.idempotency_key
            existing.experience_tier = model.experience_tier
            existing.assessment_link = model.assessment_link or existing.assessment_link
            existing.expires_at = model.expires_at or existing.expires_at
            existing.session_status = model.session_status
            existing.score_status = model.score_status
            await self.db.flush()
            return existing
        self.db.add(model)
        await self.db.flush()
        return model

    async def get_by_document_and_project(
        self, document_id: UUID, project_id: UUID
    ) -> CandidateAssessmentModel | None:
        stmt = select(CandidateAssessmentModel).where(
            CandidateAssessmentModel.document_id == document_id,
            CandidateAssessmentModel.project_id == project_id,
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_active_requisition_refs() -> list[str]:
        stmt = select(CandidateAssessmentModel.requisition_ref).distinct()
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status_by_requisition(
        self,
        requisition_ref: str,
        session_status: str,
        score_status: str,
        composite_score: float | None = None,
        composite_score_band: str | None = None,
        decision: str | None = None,
        polled_at: datetime | None = None,
        candidates: list[dict] | None = None,
    ) -> None:
        stmt = select(CandidateAssessmentModel).where(
            CandidateAssessmentModel.requisition_ref == requisition_ref
        )
        result = await self.db.execute(stmt)
        records = list(result.scalars().all())

        if candidates and isinstance(candidates, list) and len(candidates) > 0:
            await self.update_candidate_statuses_by_requisition(
                requisition_ref=requisition_ref,
                candidates_data=candidates,
                polled_at=polled_at,
                default_session_status=session_status,
                default_score_status=score_status,
                default_composite_score_band=composite_score_band,
                default_decision=decision,
            )
            return

        for record in records:
            record.session_status = session_status
            record.score_status = score_status
            if composite_score is not None:
                record.composite_score = composite_score
            if composite_score_band is not None:
                record.composite_score_band = composite_score_band
            if decision is not None:
                record.decision = decision
            if polled_at is not None:
                record.last_polled_at = polled_at
        await self.db.flush()

    async def update_candidate_statuses_by_requisition(
        self,
        requisition_ref: str,
        candidates_data: list[dict],
        polled_at: datetime | None = None,
        default_session_status: str = "not_started",
        default_score_status: str = "not_graded",
        default_composite_score_band: str | None = None,
        default_decision: str | None = None,
    ) -> None:
        stmt = select(CandidateAssessmentModel).where(
            CandidateAssessmentModel.requisition_ref == requisition_ref
        )
        result = await self.db.execute(stmt)
        records = list(result.scalars().all())

        if not records:
            return

        # Build lookup indexes
        ref_map: dict[str, CandidateAssessmentModel] = {}
        for rec in records:
            if rec.external_candidate_ref:
                ref_map[str(rec.external_candidate_ref).strip()] = rec
            if rec.document_id:
                ref_map[str(rec.document_id).strip()] = rec

        def _parse_dt(val: Any) -> datetime | None:
            if isinstance(val, datetime):
                return val
            if isinstance(val, str) and val.strip():
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                except ValueError:
                    pass
            return None

        matched_records = set()

        for idx, cdata in enumerate(candidates_data):
            if not isinstance(cdata, dict):
                continue

            c_ref = str(
                cdata.get("external_candidate_ref")
                or cdata.get("externalCandidateRef")
                or cdata.get("document_id")
                or cdata.get("documentId")
                or cdata.get("candidate_id")
                or (cdata.get("metadata", {}).get("document_id") if isinstance(cdata.get("metadata"), dict) else None)
                or ""
            ).strip()

            c_email = str(
                cdata.get("candidate_email")
                or cdata.get("candidateEmail")
                or cdata.get("email")
                or ""
            ).strip().lower()

            target_rec = ref_map.get(c_ref)

            if target_rec is None and c_email:
                for rec in records:
                    # Match against candidate_email if rec attributes or relationships match
                    pass

            if target_rec is None and idx < len(records):
                target_rec = records[idx]

            if target_rec is not None:
                matched_records.add(target_rec.id)

                sess_stat = (
                    cdata.get("session_status")
                    or cdata.get("sessionstatus")
                    or cdata.get("sessionStatus")
                    or default_session_status
                )
                score_stat = (
                    cdata.get("score_status")
                    or cdata.get("scorestatus")
                    or cdata.get("scoreStatus")
                    or default_score_status
                )
                comp_score = (
                    cdata.get("composite_score")
                    if cdata.get("composite_score") is not None
                    else (cdata.get("compositescore") if cdata.get("compositescore") is not None else cdata.get("compositeScore"))
                )
                if comp_score is not None:
                    try:
                        target_rec.composite_score = float(comp_score)
                    except (ValueError, TypeError):
                        pass

                comp_band = (
                    cdata.get("composite_score_band")
                    or cdata.get("compositescoreband")
                    or cdata.get("compositeScoreBand")
                    or cdata.get("score_band")
                    or cdata.get("scoreband")
                    or cdata.get("scoreBand")
                    or default_composite_score_band
                )
                if comp_band is not None:
                    target_rec.composite_score_band = str(comp_band)

                id_stat = (
                    cdata.get("identity_status")
                    or cdata.get("identitystatus")
                    or cdata.get("identityStatus")
                )
                if id_stat is not None:
                    target_rec.identity_status = str(id_stat)

                is_id_ver = (
                    cdata.get("is_identity_verified")
                    if cdata.get("is_identity_verified") is not None
                    else (
                        cdata.get("isidentityverified")
                        if cdata.get("isidentityverified") is not None
                        else cdata.get("isIdentityVerified")
                    )
                )
                if is_id_ver is not None:
                    target_rec.is_identity_verified = bool(is_id_ver)

                started = _parse_dt(
                    cdata.get("started_at")
                    or cdata.get("startedat")
                    or cdata.get("startedAt")
                )
                if started is not None:
                    target_rec.started_at = started

                submitted = _parse_dt(
                    cdata.get("submitted_at")
                    or cdata.get("submittedat")
                    or cdata.get("submittedAt")
                )
                if submitted is not None:
                    target_rec.submitted_at = submitted

                expires = _parse_dt(
                    cdata.get("expires_at")
                    or cdata.get("expiresat")
                    or cdata.get("expiresAt")
                )
                if expires is not None:
                    target_rec.expires_at = expires

                dec = cdata.get("decision") or default_decision
                if dec is not None:
                    target_rec.decision = str(dec)

                target_rec.session_status = str(sess_stat)
                target_rec.score_status = str(score_stat)
                if polled_at is not None:
                    target_rec.last_polled_at = polled_at

        # Fallback for un-matched records in requisition
        for rec in records:
            if rec.id not in matched_records:
                if default_session_status:
                    rec.session_status = default_session_status
                if default_score_status:
                    rec.score_status = default_score_status
                if default_composite_score_band and rec.composite_score_band is None:
                    rec.composite_score_band = default_composite_score_band
                if default_decision and rec.decision is None:
                    rec.decision = default_decision
                if polled_at is not None:
                    rec.last_polled_at = polled_at

        await self.db.flush()
