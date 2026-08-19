import asyncio
from uuid import UUID
import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.assessment import AssessmentHandoffData, CandidateAssessmentItem
from app.services.cd_recruit_service import CDRecruitService
from app.services.document_service import DocumentNotFoundException
from app.services.project_service import ProjectNotFoundException
from app.services.email_service import EmailService

logger = structlog.get_logger(__name__)


async def _dispatch_emails_background(
    email_service: EmailService,
    items_to_email: list[dict[str, str]],
    requisition_ref: str,
) -> None:
    """Send assessment invitation emails concurrently in the background."""
    async def _send_one(item: dict[str, str]) -> None:
        try:
            await email_service.send_assessment_invitation(
                candidate_name=item["candidate_name"],
                candidate_email=item["email"],
                assessment_link=item["assessment_link"],
                requisition_ref=requisition_ref,
            )
        except Exception as exc:
            logger.warning(
                "[ASSESSMENT_EMAIL] background delivery failed",
                candidate_email=item.get("email"),
                error=str(exc),
            )

    if items_to_email:
        await asyncio.gather(*[_send_one(item) for item in items_to_email], return_exceptions=True)



class AssessmentService:
    def __init__(
        self,
        projects: ProjectRepository,
        documents: DocumentRepository,
        extractions: ExtractionRepository,
        scores: ScoringRepository | None = None,
        cd_recruit: CDRecruitService | None = None,
        email_service: EmailService | None = None,
    ) -> None:
        self.projects = projects
        self.documents = documents
        self.extractions = extractions
        self.scores = scores
        self.cd_recruit = cd_recruit or CDRecruitService()
        self.email_service = email_service or EmailService(settings=self.cd_recruit.settings)


    async def handoff_assessment(
        self,
        project_id: UUID,
        candidate_ids: list[UUID],
        requisition_ref: str,
    ) -> AssessmentHandoffData:
        logger.info(
            "[ASSESSMENT_HANDOFF] starting handoff",
            project_id=str(project_id),
            requisition_ref=requisition_ref,
            candidate_count=len(candidate_ids),
        )

        try:
            project = await self.projects.get_by_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project.") from exc

        if project is None:
            raise ProjectNotFoundException()

        dept_raw = str(project.department or "").strip().upper().replace(" ", "_")
        dept_map = {
            "SOFTWARE_ENGINEERING": "SOFTWARE_ENGINEERING",
            "ENGINEERING": "SOFTWARE_ENGINEERING",
            "ENG": "SOFTWARE_ENGINEERING",
            "DATA_ENGINEERING": "DATA_ENGINEERING",
            "PMO": "PMO",
            "QA": "QA",
            "SYSOPS": "SYSOPS",
            "ITOPS": "ITOPS",
            "SECOPS": "SECOPS",
            "SRE": "SRE",
        }
        default_dept = str(
            getattr(self.cd_recruit.settings, "CD_RECRUIT_DEFAULT_DEPARTMENT_CODE", "SOFTWARE_ENGINEERING")
        ).strip()
        department_code = dept_map.get(dept_raw, default_dept)

        meta_raw = getattr(project, "metadata_json", {}) or {}
        meta = meta_raw if isinstance(meta_raw, dict) else {}

        exp_selected = str(
            meta.get("experience_level")
            or meta.get("exp_level")
            or meta.get("level")
            or ""
        ).strip().upper()

        if "FRESH" in exp_selected:
            level = "FRESHER"
        elif "EXP" in exp_selected:
            level = "EXPERIENCED"
        else:
            default_level = str(
                getattr(self.cd_recruit.settings, "CD_RECRUIT_DEFAULT_LEVEL", "EXPERIENCED")
            ).strip().upper()
            level = default_level if default_level in ("FRESHER", "EXPERIENCED") else "EXPERIENCED"

        persisted_req_ref = meta.get("req_ref") if isinstance(meta, dict) else None
        effective_req_ref = str(persisted_req_ref or requisition_ref or "").strip()
        if not effective_req_ref:
            raise BadRequestException("Requisition reference (req_ref) is required.")

        candidate_payloads = []
        candidate_meta_map = {}


        for doc_id in candidate_ids:
            try:
                document = await self.documents.get_document(doc_id)
            except SQLAlchemyError as exc:
                raise InternalServerException("Unable to retrieve candidate document.") from exc

            if document is None or document.project_id != project_id:
                raise DocumentNotFoundException(f"Candidate document {doc_id} not found in this project.")

            try:
                extracted = await self.extractions.get_resume_by_document_id(doc_id)
            except SQLAlchemyError as exc:
                raise InternalServerException("Unable to retrieve candidate extracted info.") from exc

            ai_score = 0.0
            if self.scores is not None:
                try:
                    score_model = await self.scores.get_document_score(doc_id)
                    if score_model is not None and score_model.final_score is not None:
                        ai_score = float(score_model.final_score)
                except SQLAlchemyError as exc:
                    logger.warning("[ASSESSMENT_HANDOFF] unable to fetch score", document_id=str(doc_id), error=str(exc))

            orig_filename = getattr(document, "original_filename", None) or f"document_{str(doc_id)[:8]}.pdf"

            c_name = getattr(extracted, "candidate_name", None) if extracted else None
            candidate_name = c_name or orig_filename or f"Candidate {str(doc_id)[:8]}"

            c_email = getattr(extracted, "email", None) if extracted else None
            email = c_email or f"candidate_{str(doc_id)[:8]}@example.com"

            phone = getattr(extracted, "phone", "") if extracted and getattr(extracted, "phone", None) else ""

            candidate_payloads.append({
                "name": candidate_name,
                "email": email,
                "phone": phone,
                "ai_score": ai_score,
                "metadata": {
                    "document_id": str(doc_id),
                    "original_filename": orig_filename,
                },
            })
            candidate_meta_map[str(doc_id)] = {
                "candidate_name": candidate_name,
                "email": email,
            }


        # Call CD-Recruit partner service
        cd_results = await self.cd_recruit.send_candidates(
            department_code=department_code,
            level=level,
            requisition_ref=effective_req_ref,
            candidates=candidate_payloads,
        )


        # Map CD-Recruit response back to candidate items
        cd_map = {}
        if isinstance(cd_results, list):
            for item in cd_results:
                if isinstance(item, dict):
                    c_email = str(item.get("candidate_email") or item.get("email") or "").strip().lower()
                    if c_email:
                        cd_map[c_email] = item

        items: list[CandidateAssessmentItem] = []
        for i, doc_id in enumerate(candidate_ids):
            meta = candidate_meta_map.get(str(doc_id), {})
            cand_email = str(meta.get("email", "")).strip().lower()
            cd_item = cd_map.get(cand_email) or (cd_results[i] if i < len(cd_results) and isinstance(cd_results[i], dict) else {})
            assessment_link = (
                cd_item.get("assessment_link")
                or cd_item.get("assessmentUrl")
                or cd_item.get("assessmentLink")
                or cd_item.get("inviteUrl")
                or cd_item.get("link")
                or cd_item.get("assessment_url")
                or cd_item.get("test_url")
                or cd_item.get("url")
            )

            items.append(
                CandidateAssessmentItem(
                    candidate_id=doc_id,
                    candidate_name=meta.get("candidate_name", "Candidate"),
                    email=meta.get("email", ""),
                    assessment_link=assessment_link,
                    status="INVITED",
                )
            )


        # Dispatch assessment invitation emails asynchronously in background task
        if getattr(self.cd_recruit.settings, "ENABLE_ASSESSMENT_EMAILS", True):
            items_to_email = [
                {
                    "candidate_name": item.candidate_name,
                    "email": item.email,
                    "assessment_link": item.assessment_link,
                }
                for item in items
                if item.assessment_link and item.email and item.email.strip()
            ]
            if items_to_email:
                asyncio.create_task(
                    _dispatch_emails_background(
                        self.email_service, items_to_email, effective_req_ref
                    )
                )


        logger.info(
            "[ASSESSMENT_HANDOFF] handoff completed successfully",
            project_id=str(project_id),
            total_invited=len(items),
        )


        return AssessmentHandoffData(
            project_id=project_id,
            requisition_ref=requisition_ref,
            total_invited=len(items),
            candidates=items,
        )
