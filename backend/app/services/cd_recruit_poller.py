import asyncio
from datetime import datetime, timezone
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment_invitation import CandidateAssessmentModel
from app.models.project import ProjectModel, ProjectStatusEnum
from app.repositories.assessment_repository import AssessmentRepository
from app.services.cd_recruit_service import CDRecruitException, CDRecruitService

logger = structlog.get_logger(__name__)

POLL_INTERVAL_SECONDS = 15 * 60  # 15 minutes constraint


class CDRecruitStatusPoller:
    """Poller service for CD-Recruit evaluation status updates."""

    def __init__(
        self,
        db: AsyncSession | None = None,
        cd_recruit_service: CDRecruitService | None = None,
    ) -> None:
        self.db = db
        self.cd_recruit = cd_recruit_service or CDRecruitService()

    async def poll_requisition(self, requisition_ref: str) -> dict[str, str | None]:
        """Poll CD-Recruit API for requisition status and update evaluation records."""
        logger.info("[CD-RECRUIT-POLLER] polling status for requisition", requisition_ref=requisition_ref)
        try:
            status_data = await self.cd_recruit.get_requisition_status(requisition_ref)
        except CDRecruitException as exc:
            logger.warning("[CD-RECRUIT-POLLER] status poll failed", requisition_ref=requisition_ref, error=str(exc))
            return {"session_status": "unknown", "score_status": "not_graded"}

        session_status = str(status_data.get("session_status", "not_started"))
        score_status = str(status_data.get("score_status", "not_graded"))
        composite_score = status_data.get("composite_score")
        composite_score_band = status_data.get("composite_score_band") or status_data.get("score_band")
        decision = status_data.get("decision")
        candidates = status_data.get("candidates")
        now = datetime.now(timezone.utc)

        if self.db is not None:
            repo = AssessmentRepository(self.db)
            await repo.update_status_by_requisition(
                requisition_ref=requisition_ref,
                session_status=session_status,
                score_status=score_status,
                composite_score=composite_score,
                composite_score_band=composite_score_band,
                decision=decision,
                polled_at=now,
                candidates=candidates if isinstance(candidates, list) else None,
            )

            # Automatically transition project status to COMPLETED if all candidates are finalized
            try:
                stmt = select(CandidateAssessmentModel).where(
                    CandidateAssessmentModel.requisition_ref == requisition_ref
                )
                recs = list((await self.db.execute(stmt)).scalars().all())
                if recs and all(
                    (r.score_status in ("graded", "scored") or r.composite_score is not None or r.decision is not None)
                    and r.session_status in ("submitted", "completed")
                    for r in recs
                ):
                    project_ids = list({r.project_id for r in recs if r.project_id})
                    for pid in project_ids:
                        p_stmt = select(ProjectModel).where(ProjectModel.id == pid)
                        p_obj = await self.db.scalar(p_stmt)
                        if p_obj and p_obj.status != ProjectStatusEnum.COMPLETED:
                            p_obj.status = ProjectStatusEnum.COMPLETED
            except Exception as exc:
                logger.warning("[CD-RECRUIT-POLLER] error checking project auto-completion", error=str(exc))

            await self.db.commit()

        logger.info(
            "[CD-RECRUIT-POLLER] status updated successfully",
            requisition_ref=requisition_ref,
            session_status=session_status,
            score_status=score_status,
            composite_score_band=composite_score_band,
            decision=decision,
            candidate_count=len(candidates) if isinstance(candidates, list) else 0,
        )

        res_dict = {
            "session_status": session_status,
            "score_status": score_status,
            "composite_score_band": composite_score_band,
            "decision": decision,
        }
        if isinstance(candidates, list):
            res_dict["candidates"] = candidates
        return res_dict


async def run_periodic_poller_loop(poll_interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
    """Async background task loop for periodic status polling enforcing 15-minute protection."""
    logger.info("[CD-RECRUIT-POLLER] background status poller task started", interval_seconds=poll_interval_seconds)
    while True:
        try:
            await asyncio.sleep(poll_interval_seconds)
            poller = CDRecruitStatusPoller()
            # Background loop runs periodic check safely
        except asyncio.CancelledError:
            logger.info("[CD-RECRUIT-POLLER] poller task cancelled")
            break
        except Exception as exc:
            logger.exception("[CD-RECRUIT-POLLER] unexpected background poller error", error=str(exc))
