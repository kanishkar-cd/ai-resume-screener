from datetime import datetime
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
        composite_score_band: str | None = None,
        decision: str | None = None,
        polled_at: datetime | None = None,
    ) -> None:
        stmt = select(CandidateAssessmentModel).where(
            CandidateAssessmentModel.requisition_ref == requisition_ref
        )
        result = await self.db.execute(stmt)
        records = result.scalars().all()
        for record in records:
            record.session_status = session_status
            record.score_status = score_status
            if composite_score_band is not None:
                record.composite_score_band = composite_score_band
            if decision is not None:
                record.decision = decision
            if polled_at is not None:
                record.last_polled_at = polled_at
        await self.db.flush()
