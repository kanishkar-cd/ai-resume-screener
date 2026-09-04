import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, ValidationException, InternalServerException
from app.models.assessment_invitation import CandidateAssessmentModel
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.assessment import AssessmentHandoffData, CandidateAssessmentItem
from app.schemas.project import ProjectStatus, ProjectUpdate
from app.services.cd_recruit_mapper import calibrate_experience, map_department_code
from app.services.cd_recruit_service import CDRecruitService
from app.services.document_service import DocumentNotFoundException
from app.services.email_service import EmailService
from app.services.project_service import ProjectNotFoundException

logger = structlog.get_logger(__name__)


async def _dispatch_emails_background(
    email_service: EmailService,
    items_to_email: list[dict[str, str]],
    requisition_ref: str,
    provider: str = "ses",
) -> None:
    """Send assessment invitation emails concurrently in the background."""
    async def _send_one(item: dict[str, str]) -> None:
        try:
            await email_service.send_assessment_invitation(
                candidate_name=item["candidate_name"],
                candidate_email=item["email"],
                assessment_link=item["assessment_link"],
                requisition_ref=requisition_ref,
                provider=provider or "ses",
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
        assessments: AssessmentRepository | None = None,
    ) -> None:
        self.projects = projects
        self.documents = documents
        self.extractions = extractions
        self.scores = scores
        self.cd_recruit = cd_recruit or CDRecruitService()
        self.email_service = email_service or EmailService(settings=self.cd_recruit.settings)
        self.assessments = assessments

    async def handoff_assessment(
        self,
        project_id: UUID,
        candidate_ids: list[UUID],
        requisition_ref: str,
        provider: str = "ses",
    ) -> AssessmentHandoffData:
        logger.info(
            "[ASSESSMENT_HANDOFF] starting handoff",
            project_id=str(project_id),
            requisition_ref=requisition_ref,
            candidate_count=len(candidate_ids),
            provider=provider,
        )

        try:
            project = await self.projects.get_by_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project.") from exc

        if project is None:
            raise ProjectNotFoundException()

        meta_raw = getattr(project, "metadata_json", {}) or {}
        meta = meta_raw if isinstance(meta_raw, dict) else {}

        # Requisition stability: Use project.id or stored req_ref
        persisted_req_ref = meta.get("req_ref")
        effective_req_ref = str(persisted_req_ref or requisition_ref or f"REQ-{project.id}").strip()

        # Department mapping to 8 strict codes
        department_code = map_department_code(
            project.department,
            default_code=getattr(self.cd_recruit.settings, "CD_RECRUIT_DEFAULT_DEPARTMENT_CODE", "SOFTWARE_ENGINEERING")
        )

        drive_name = f"{project.title} Drive" if getattr(project, "title", None) else "Candidate Handoff Drive"

        # Generate single batch idempotency key for this logical batch request
        batch_idempotency_key = str(uuid4())

        candidate_payloads = []
        candidate_meta_map = {}
        exp_meta = str(meta.get("experience_level") or meta.get("level") or "").upper()
        if "EXP" in exp_meta:
            batch_category = "EXPERIENCED"
        elif "FRESH" in exp_meta:
            batch_category = "FRESHER"
        else:
            batch_category = "FRESHER"

        async def _load_candidate(doc_id: UUID) -> dict[str, Any]:
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

            orig_filename = getattr(document, "original_filename", None) or f"document_{str(doc_id)[:8]}.pdf"
            candidate_name = (getattr(extracted, "candidate_name", None) if extracted else None) or orig_filename
            email = (getattr(extracted, "email", None) if extracted else None) or f"candidate_{str(doc_id)[:8]}@example.com"
            phone = getattr(extracted, "phone", "") if extracted and getattr(extracted, "phone", None) else ""

            exp_items = (getattr(extracted, "experience", None) if extracted else None) or []
            total_months = sum(item.get("duration_months") or 0 for item in exp_items if isinstance(item, dict))

            category, experience_tier = calibrate_experience(total_months)

            ai_score = 0.0
            if self.scores is not None:
                try:
                    score_model = await self.scores.get_document_score(doc_id)
                    if score_model is not None and score_model.final_score is not None:
                        ai_score = float(score_model.final_score)
                except Exception as exc:
                    logger.warning("[ASSESSMENT_HANDOFF] unable to fetch candidate score", document_id=str(doc_id), error=str(exc))

            exp_years = round(total_months / 12.0, 1)

            return {
                "doc_id": doc_id,
                "candidate_name": candidate_name,
                "email": email,
                "phone": phone,
                "ai_score": ai_score,
                "orig_filename": orig_filename,
                "experience_tier": experience_tier,
                "total_months": total_months,
                "exp_years": exp_years,
                "category": category,
            }

        extracted_candidates_data = await asyncio.gather(*[_load_candidate(doc_id) for doc_id in candidate_ids])

        for cdata in extracted_candidates_data:
            if cdata["category"] == "EXPERIENCED":
                batch_category = "EXPERIENCED"

        for cdata in extracted_candidates_data:
            doc_id = cdata["doc_id"]
            experience_tier = cdata["experience_tier"]

            if batch_category == "EXPERIENCED":
                cand_level = experience_tier if experience_tier in ("2-5", "6-10", "11-15") else "2-5"
            else:
                cand_level = "0-1"

            cand_payload: dict[str, Any] = {
                "name": cdata["candidate_name"],
                "email": cdata["email"],
                "level": cand_level,
                "external_candidate_ref": str(doc_id),
                "metadata": {
                    "document_id": str(doc_id),
                    "original_filename": cdata["orig_filename"],
                    "experience_tier": cand_level,
                    "experience_months": cdata["total_months"],
                    "experience_years": cdata["exp_years"],
                    "category": batch_category,
                    "ai_score": cdata["ai_score"],
                },
            }
            if cdata.get("phone"):
                cand_payload["phone"] = cdata["phone"]

            candidate_payloads.append(cand_payload)
            candidate_meta_map[str(doc_id)] = {
                "candidate_name": cdata["candidate_name"],
                "email": cdata["email"],
                "level": cand_level,
                "experience_tier": cand_level,
                "experience_months": cdata["total_months"],
                "category": batch_category,
            }

        # Call local CD-Recruit partner service (returns HTTP 201 Created)
        cd_response = await self.cd_recruit.send_candidates(
            department_code,
            batch_category,
            effective_req_ref,
            candidate_payloads,
        )

        logger.info("[CD-RECRUIT] response payload received from partner API", cd_response=cd_response)

        drive_id = cd_response.get("drive_id") or cd_response.get("driveId") if isinstance(cd_response, dict) else None

        # Parse invites response
        cd_results = []
        if isinstance(cd_response, dict):
            inner_data = cd_response.get("data")
            if isinstance(inner_data, dict):
                cd_results = inner_data.get("invites") or inner_data.get("candidates") or [inner_data]
            elif isinstance(inner_data, list):
                cd_results = inner_data
            else:
                cd_results = cd_response.get("invites") or cd_response.get("candidates") or [cd_response]
        elif isinstance(cd_response, list):
            cd_results = cd_response

        cd_map = {}
        if isinstance(cd_results, list):
            for item in cd_results:
                if isinstance(item, dict):
                    ext_ref = str(
                        item.get("external_candidate_ref")
                        or item.get("externalCandidateRef")
                        or (item.get("metadata", {}).get("document_id") if isinstance(item.get("metadata"), dict) else None)
                        or ""
                    ).strip()
                    c_email = str(
                        item.get("candidate_email")
                        or item.get("candidateEmail")
                        or item.get("email")
                        or ""
                    ).strip().lower()
                    if ext_ref:
                        cd_map[ext_ref] = item
                    if c_email:
                        cd_map[c_email] = item

        items: list[CandidateAssessmentItem] = []
        assessment_models_to_persist = []
        for i, doc_id in enumerate(candidate_ids):
            meta_item = candidate_meta_map.get(str(doc_id), {})
            cand_email = str(meta_item.get("email", "")).strip().lower()
            cd_item = cd_map.get(str(doc_id)) or cd_map.get(cand_email) or (cd_results[i] if i < len(cd_results) and isinstance(cd_results[i], dict) else {})

            assessment_link = (
                cd_item.get("assessment_link")
                or cd_item.get("assessmentLink")
                or cd_item.get("assessment_url")
                or cd_item.get("assessmentUrl")
                or cd_item.get("invite_url")
                or cd_item.get("inviteUrl")
                or cd_item.get("invite_link")
                or cd_item.get("inviteLink")
                or cd_item.get("link")
                or cd_item.get("url")
            )
            if not assessment_link and (token := cd_item.get("token") or cd_item.get("invite_token")):
                base = self.cd_recruit.settings.CD_RECRUIT_BASE_URL.rstrip("/")
                assessment_link = f"{base}/assessment/{token}"

            raw_exp = cd_item.get("expires_at") or cd_item.get("expiresAt")
            expires_at = None
            if isinstance(raw_exp, datetime):
                expires_at = raw_exp
            elif isinstance(raw_exp, str) and raw_exp.strip():
                try:
                    expires_at = datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
                except ValueError:
                    pass

            items.append(
                CandidateAssessmentItem(
                    candidate_id=doc_id,
                    candidate_name=meta_item.get("candidate_name", "Candidate"),
                    email=meta_item.get("email", ""),
                    assessment_link=assessment_link,
                    status="INVITED",
                )
            )

            if self.assessments is not None and assessment_link:
                assessment_models_to_persist.append(
                    CandidateAssessmentModel(
                        project_id=project_id,
                        document_id=doc_id,
                        requisition_ref=effective_req_ref,
                        drive_id=drive_id,
                        external_candidate_ref=str(doc_id),
                        idempotency_key=batch_idempotency_key,
                        experience_tier=meta_item.get("experience_tier"),
                        assessment_link=assessment_link,
                        expires_at=expires_at,
                        session_status="not_started",
                        score_status="not_graded",
                    )
                )

        if assessment_models_to_persist and self.assessments is not None:
            async def _persist_one(model: CandidateAssessmentModel) -> None:
                try:
                    await self.assessments.create_or_update_assessment(model)
                except Exception as exc:
                    logger.warning("[ASSESSMENT_HANDOFF] unable to persist assessment record", document_id=str(model.document_id), error=str(exc))

            await asyncio.gather(*[_persist_one(model) for model in assessment_models_to_persist])

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
                        self.email_service, items_to_email, effective_req_ref, provider
                    )
                )

        # Update project status to COMPLETED upon successful assessment handoff
        if items and hasattr(self.projects, "update"):
            update_res = self.projects.update(
                project_id, ProjectUpdate(status=ProjectStatus.COMPLETED)
            )
            if asyncio.iscoroutine(update_res):
                await update_res

        logger.info(
            "[ASSESSMENT_HANDOFF] handoff completed successfully",
            project_id=str(project_id),
            total_invited=len(items),
            drive_id=drive_id,
        )

        return AssessmentHandoffData(
            project_id=project_id,
            requisition_ref=effective_req_ref,
            total_invited=len(items),
            candidates=items,
        )
