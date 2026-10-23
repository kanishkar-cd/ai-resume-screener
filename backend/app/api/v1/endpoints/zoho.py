from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path as FastApiPath, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
import structlog

from app.api.deps import DatabaseDependency
from app.api.v1.endpoints.documents import get_document_service
from app.core.config import get_settings
from app.models.document import (
    DocumentModel,
    DocumentTypeEnum,
    ProcessingStageEnum,
    ProcessingStatusEnum,
)
from app.models.extracted_job_description import ExtractedJDModel
from app.models.normalized_job_description import NormalizedJDModel
from app.models.parsed_document import ParsedDocumentModel
from app.repositories.document_repository import DocumentRepository
from app.repositories.extracted_jd_repository import ExtractedJDRepository
from app.repositories.normalized_jd_repository import NormalizedJDRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import (
    DocumentResponse,
    DocumentType,
    JobDescriptionProcessRead,
    JobDescriptionProcessResponse,
    ProcessingStage,
    ProcessingStatus,
)
from app.schemas.error import ErrorResponsePayload
from app.schemas.extracted_jd import ExtractedJDRead
from app.schemas.normalized_jd import NormalizedJDRead
from app.schemas.zoho import (
    ZohoFetchSummary,
    ZohoImportApplicantsRequest,
    ZohoImportApplicantsResponse,
    ZohoImportJDRequest,
    ZohoJobOpeningListResponse,
    ZohoJobOpeningRead,
    ZohoStatusResponse,
)
from app.services.document_service import DocumentService, InternalServerException
from app.services.jd_extraction_service import JDExtractionService
from app.services.jd_normalization_service import JDNormalizationService
from app.services.parsing_service import ParsingService
from app.services.project_service import ProjectNotFoundException
from app.services.storage_service import StorageService
from app.services.zoho_recruit_service import (
    ZohoJobOpening,
    ZohoRecruitClient,
    ZohoRecruitException,
    ZohoRecruitNotConfiguredException,
    normalize_html_to_text,
)

logger = structlog.get_logger(__name__)

router = APIRouter()
ProjectId = Annotated[UUID, FastApiPath(examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])]


@lru_cache(maxsize=1)
def get_zoho_client() -> ZohoRecruitClient:
    return ZohoRecruitClient()


ZohoClientDependency = Annotated[ZohoRecruitClient, Depends(get_zoho_client)]


@router.get(
    "/zoho/status",
    response_model=ZohoStatusResponse,
    summary="Get Zoho integration status",
    description="Check whether Zoho credentials and OAuth tokens are configured in the backend environment.",
)
async def get_zoho_status(
    client: ZohoClientDependency,
) -> ZohoStatusResponse:
    settings = get_settings()
    return ZohoStatusResponse(
        configured=client.configured,
        accounts_url=settings.ZOHO_ACCOUNTS_URL,
        api_url=settings.ZOHO_RECRUIT_API_URL,
        has_job_token=bool(settings.ZOHO_JOB_OPENINGS_REFRESH_TOKEN or settings.ZOHO_REFRESH_TOKEN),
        has_candidate_token=bool(settings.ZOHO_CANDIDATES_REFRESH_TOKEN or settings.ZOHO_REFRESH_TOKEN),
        has_attachment_token=bool(settings.ZOHO_ATTACHMENTS_REFRESH_TOKEN or settings.ZOHO_REFRESH_TOKEN),
    )


@router.get(
    "/zoho/job-openings",
    response_model=ZohoJobOpeningListResponse,
    summary="List Zoho Job Openings",
    description="Fetch active job postings (JDs) directly from Zoho Recruit.",
    responses={
        502: {"model": ErrorResponsePayload, "description": "Zoho API integration failed."},
        503: {"model": ErrorResponsePayload, "description": "Zoho credentials not configured."},
    },
)
async def list_zoho_job_openings(
    client: ZohoClientDependency,
    status_filter: Annotated[str | None, Query(alias="status", description="Filter by status (e.g., In-progress, Open)")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Max job openings to return")] = 50,
) -> ZohoJobOpeningListResponse:
    if not client.configured:
        raise ZohoRecruitNotConfiguredException("Zoho Recruit credentials are not configured in backend/.env.")
    try:
        items: list[ZohoJobOpeningRead] = []
        async for job in client.iter_job_openings(status=status_filter):
            items.append(
                ZohoJobOpeningRead(
                    id=job.id,
                    posting_title=job.posting_title,
                    job_opening_id=job.job_opening_id,
                    job_description=job.job_description,
                    required_skills=job.required_skills,
                    job_status=job.job_status,
                    target_date=job.target_date,
                    city=job.city,
                    department=job.department,
                    modified_time=job.modified_time,
                    no_of_candidates_associated=job.no_of_candidates_associated,
                )
            )
            if len(items) >= limit:
                break
        return ZohoJobOpeningListResponse(items=items, total=len(items))
    except ZohoRecruitException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get(
    "/zoho/job-openings/{job_id}",
    response_model=ZohoJobOpeningRead,
    summary="Get Zoho Job Opening Details",
    description="Fetch a single Job Opening details and description from Zoho Recruit.",
)
async def get_zoho_job_opening(
    job_id: Annotated[str, FastApiPath(description="Zoho Job Opening ID")],
    client: ZohoClientDependency,
) -> ZohoJobOpeningRead:
    if not client.configured:
        raise ZohoRecruitNotConfiguredException("Zoho Recruit credentials are not configured in backend/.env.")
    try:
        job = await client.get_job_opening(job_id)
        return ZohoJobOpeningRead(
            id=job.id,
            posting_title=job.posting_title,
            job_opening_id=job.job_opening_id,
            job_description=job.job_description,
            required_skills=job.required_skills,
            job_status=job.job_status,
            target_date=job.target_date,
            city=job.city,
            department=job.department,
            modified_time=job.modified_time,
            no_of_candidates_associated=job.no_of_candidates_associated,
        )
    except ZohoRecruitException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/projects/{project_id}/zoho/import-jd",
    response_model=JobDescriptionProcessResponse,
    status_code=status.HTTP_200_OK,
    summary="Import Zoho Job Description into Project",
    description="Fetch a Job Description from Zoho Recruit and process it end-to-end (Parse -> Extract -> Normalize) into the project.",
    responses={
        404: {"model": ErrorResponsePayload, "description": "Project not found."},
        502: {"model": ErrorResponsePayload, "description": "Zoho API integration failed."},
        503: {"model": ErrorResponsePayload, "description": "Zoho credentials not configured."},
    },
)
async def import_zoho_job_description(
    project_id: ProjectId,
    request: ZohoImportJDRequest,
    db: DatabaseDependency,
    client: ZohoClientDependency,
) -> JobDescriptionProcessResponse:
    if not client.configured:
        raise ZohoRecruitNotConfiguredException("Zoho Recruit credentials are not configured in backend/.env.")

    # 1. Verify project exists
    project_repo = ProjectRepository(db)
    project = await project_repo.get_by_id(project_id)
    if project is None:
        raise ProjectNotFoundException()

    # 2. Fetch Job Opening from Zoho
    try:
        job = await client.get_job_opening(request.job_id)
    except ZohoRecruitException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # 3. Assemble full text content for the JD
    full_text_lines = [f"Job Title: {job.posting_title}"]
    if job.job_opening_id:
        full_text_lines.append(f"Job Code: {job.job_opening_id}")
    if job.department:
        full_text_lines.append(f"Department: {job.department}")
    if job.required_skills:
        clean_skills = normalize_html_to_text(job.required_skills)
        if clean_skills:
            full_text_lines.append(f"Required Skills: {clean_skills}")
    if job.job_description:
        clean_desc = normalize_html_to_text(job.job_description)
        if clean_desc:
            full_text_lines.append(f"\nDescription:\n{clean_desc}")
    
    jd_raw_text = "\n".join(full_text_lines)
    content_bytes = jd_raw_text.encode("utf-8")

    # 4. Save to Storage
    storage_service = StorageService()
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", job.posting_title)
    original_filename = f"Zoho_JD_{job.id}_{safe_title}.txt"
    stored_filename, file_path, file_size_bytes, file_hash = storage_service.save_bytes(
        content=content_bytes,
        project_id=project_id,
        subfolder="job_description",
        extension=".txt",
    )

    now = datetime.now(UTC)
    doc_id = uuid4()
    doc_repo = DocumentRepository(db)

    # Clean up any prior active JD for this project
    prior_jd_stmt = select(DocumentModel).where(
        DocumentModel.project_id == project_id,
        DocumentModel.document_type == DocumentTypeEnum.JOB_DESCRIPTION,
        DocumentModel.deleted_at.is_(None),
    )
    prior_result = await db.execute(prior_jd_stmt)
    prior_jd_record = prior_result.scalars().first()
    if prior_jd_record is not None:
        prior_jd_record.deleted_at = now
        db.add(prior_jd_record)

    # Create new document record
    doc_model = DocumentModel(
        id=doc_id,
        project_id=project_id,
        document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_path=file_path,
        file_size_bytes=file_size_bytes,
        file_hash=file_hash,
        mime_type="text/plain",
        processing_status=ProcessingStatusEnum.COMPLETED,
        processing_stage=ProcessingStageEnum.NORMALIZATION,
        created_at=now,
        updated_at=now,
    )
    db.add(doc_model)

    # Parsed document model
    word_count = len(jd_raw_text.split())
    character_count = len(jd_raw_text)
    parsed_id = uuid4()
    parsed_model = ParsedDocumentModel(
        id=parsed_id,
        document_id=doc_id,
        raw_text=jd_raw_text,
        normalized_text=jd_raw_text,
        page_count=1,
        word_count=word_count,
        character_count=character_count,
        parser_engine="PLAIN_TEXT",
        parsing_duration_ms=0.0,
        created_at=now,
        updated_at=now,
    )
    db.add(parsed_model)

    # In-memory Extraction
    parsed_repo = ParsedDocumentRepository(db)
    extracted_repo = ExtractedJDRepository(db)
    jd_extract_service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    extracted_create = await jd_extract_service.extract_from_raw_text(
        raw_text=jd_raw_text,
        document_id=doc_id,
        source_word_count=word_count,
    )
    extracted_id = uuid4()
    extracted_data = extracted_create.model_dump(exclude={"document_id"})
    extracted_model = ExtractedJDModel(
        id=extracted_id,
        document_id=doc_id,
        created_at=now,
        updated_at=now,
        **extracted_data,
    )
    db.add(extracted_model)

    # In-memory Normalization
    normalized_repo = NormalizedJDRepository(db)
    jd_norm_service = JDNormalizationService(doc_repo, extracted_repo, normalized_repo)
    normalized_create = jd_norm_service.normalize_from_extracted(
        extracted=extracted_create,
        document_id=doc_id,
        extracted_id=extracted_id,
    )
    normalized_id = uuid4()
    normalized_data = normalized_create.model_dump(exclude={"document_id", "extracted_job_description_id"})
    normalized_model = NormalizedJDModel(
        id=normalized_id,
        document_id=doc_id,
        extracted_job_description_id=extracted_id,
        created_at=now,
        updated_at=now,
        **normalized_data,
    )
    db.add(normalized_model)

    # Commit atomically
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        storage_service.delete_file(file_path)
        logger.exception("zoho_jd_import_commit_failed", document_id=str(doc_id), error=str(exc))
        raise InternalServerException("Unable to persist Zoho Job Description pipeline results.") from exc

    if prior_jd_record is not None:
        try:
            storage_service.delete_file(prior_jd_record.file_path)
        except Exception:
            logger.exception("prior_jd_file_cleanup_failed", document_id=str(prior_jd_record.id))

    extracted_read = ExtractedJDRead(
        id=extracted_id,
        document_id=doc_id,
        created_at=now,
        updated_at=now,
        **extracted_data,
    )
    normalized_read = NormalizedJDRead(
        id=normalized_id,
        document_id=doc_id,
        extracted_job_description_id=extracted_id,
        created_at=now,
        updated_at=now,
        **normalized_data,
    )

    return JobDescriptionProcessResponse(
        data=JobDescriptionProcessRead(
            document_id=doc_id,
            project_id=project_id,
            filename=doc_model.original_filename,
            processing_stage=ProcessingStage.COMPLETED,
            processing_status=ProcessingStatus.COMPLETED,
            extracted=extracted_read.model_dump(mode="json"),
            normalized=normalized_read.model_dump(mode="json"),
        )
    )


_PROJECT_SYNC_LOCKS: dict[UUID, asyncio.Lock] = {}
_PROJECT_SYNC_LOCKS: dict[UUID, asyncio.Lock] = {}
_PROJECT_SYNC_LOCK_MUTEX = asyncio.Lock()
_JOB_SYNC_LOCKS: dict[str, asyncio.Lock] = {}
_JOB_SYNC_LOCK_MUTEX = asyncio.Lock()


async def _get_project_sync_lock(project_id: UUID) -> asyncio.Lock:
    async with _PROJECT_SYNC_LOCK_MUTEX:
        if project_id not in _PROJECT_SYNC_LOCKS:
            _PROJECT_SYNC_LOCKS[project_id] = asyncio.Lock()
        return _PROJECT_SYNC_LOCKS[project_id]


async def _get_job_sync_lock(job_id: str) -> asyncio.Lock:
    async with _JOB_SYNC_LOCK_MUTEX:
        if job_id not in _JOB_SYNC_LOCKS:
            _JOB_SYNC_LOCKS[job_id] = asyncio.Lock()
        return _JOB_SYNC_LOCKS[job_id]


@router.post(
    "/projects/{project_id}/zoho/import-applicants",
    response_model=ZohoImportApplicantsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import Zoho Candidate Resumes into Project",
    description="Fetch and download candidate resumes applied to a Zoho Job Opening and attach newly discovered resumes to the project.",
    responses={
        404: {"model": ErrorResponsePayload, "description": "Project not found."},
        502: {"model": ErrorResponsePayload, "description": "Zoho API integration failed."},
        503: {"model": ErrorResponsePayload, "description": "Zoho credentials not configured."},
    },
)
async def import_zoho_applicants(
    project_id: ProjectId,
    request: ZohoImportApplicantsRequest,
    db: DatabaseDependency,
    client: ZohoClientDependency,
) -> ZohoImportApplicantsResponse:
    if not client.configured:
        raise ZohoRecruitNotConfiguredException("Zoho Recruit credentials are not configured in backend/.env.")

    # 1. Acquire per-project and per-job locks to serialize concurrent syncs
    project_lock = await _get_project_sync_lock(project_id)
    job_lock = await _get_job_sync_lock(str(request.job_id))
    async with project_lock, job_lock:
        # 2. Verify project
        project_repo = ProjectRepository(db)
        project = await project_repo.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundException()

        # 3. Query existing active resumes across the ATS (global deduplication)
        existing_stmt = select(DocumentModel).where(
            DocumentModel.document_type == DocumentTypeEnum.RESUME,
            DocumentModel.deleted_at.is_(None),
        )
        existing_docs = (await db.scalars(existing_stmt)).all()

        job_id_str = str(request.job_id)
        job_opening = None
        valid_job_ids = {job_id_str}
        try:
            job_opening = await client.get_job_opening(request.job_id)
            if job_opening.id:
                valid_job_ids.add(str(job_opening.id))
            if job_opening.job_opening_id:
                valid_job_ids.add(str(job_opening.job_opening_id))
        except Exception as job_err:
            logger.warning("zoho_get_job_opening_details_warning", job_id=job_id_str, error=str(job_err))

        existing_candidates: dict[str, str | None] = {}
        existing_attachment_ids: dict[str, str | None] = {}
        existing_hashes: set[str] = set()
        failed_attachment_docs: dict[str, DocumentModel] = {}
        total_active_resumes_for_job = 0

        for doc in existing_docs:
            if doc.file_hash:
                existing_hashes.add(doc.file_hash)
            meta = doc.metadata_json or {}
            att_id = str(meta.get("zoho_attachment_id") or "")
            att_mod = meta.get("zoho_attachment_modified_time")
            cand_id = str(meta.get("zoho_candidate_id") or "")
            cand_mod = meta.get("zoho_candidate_modified_time")
            doc_job_id = str(meta.get("zoho_job_opening_id") or "")
            doc_job_code = str(meta.get("zoho_job_opening_code") or "")

            # Deduplication scoped specifically to the selected Zoho Job Opening
            is_same_job = (
                doc_job_id in valid_job_ids
                or (doc_job_code and doc_job_code in valid_job_ids)
                or (not doc_job_id and bool(att_id))
            )
            if is_same_job:
                if doc.processing_status == ProcessingStatusEnum.FAILED:
                    if att_id:
                        failed_attachment_docs[att_id] = doc
                else:
                    total_active_resumes_for_job += 1
                    if att_id:
                        existing_attachment_ids[att_id] = att_mod
                    if cand_id:
                        existing_candidates[cand_id] = cand_mod
            else:
                # Active resumes from other jobs in the ATS: track attachment ID so attachments aren't re-downloaded
                if doc.processing_status != ProcessingStatusEnum.FAILED and att_id:
                    existing_attachment_ids[att_id] = att_mod

        # 4. Fetch applicant resumes from Zoho with already-imported candidates & attachment IDs
        try:
            fetch_result = await client.fetch_job_with_applicant_resumes(
                job_id=request.job_id,
                limit=request.limit,
                existing_attachment_ids=existing_attachment_ids,
                existing_candidates=existing_candidates,
            )
        except ZohoRecruitException as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

        storage_service = StorageService()
        now = datetime.now(UTC)
        saved_document_ids: list[UUID] = []
        created_file_paths: list[str] = []
        doc_repo = DocumentRepository(db)

        try:
            canonical_job_id = str(job_opening.id) if (job_opening and job_opening.id) else job_id_str
            opening_code = (job_opening.job_opening_id if job_opening else None) or None

            # Associate project with this Zoho Job Opening
            project.metadata_json = {
                **(project.metadata_json or {}),
                "zoho_job_opening_id": canonical_job_id,
                "zoho_job_opening_code": opening_code,
                "zoho_job_opening_title": job_opening.posting_title if job_opening else None,
            }

            for resume in fetch_result.resumes:
                att_id = str(resume.attachment.id)

                # If this attachment was previously failed, clean up the old failed document
                if att_id in failed_attachment_docs:
                    old_doc = failed_attachment_docs[att_id]
                    try:
                        storage_service.delete_file(old_doc.file_path)
                    except Exception:
                        pass
                    await doc_repo.cleanup_pipeline_data(old_doc.id, DocumentType.RESUME)
                    await db.delete(old_doc)
                    await db.flush()
                    if old_doc.file_hash in existing_hashes:
                        existing_hashes.remove(old_doc.file_hash)

                doc_id = uuid4()
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", resume.file_name)
                original_filename = f"{resume.candidate_id}_{safe_name}"

                stored_filename, file_path, file_size, file_hash = storage_service.save_bytes(
                    content=resume.content,
                    project_id=project_id,
                    subfolder="resumes",
                    extension=resume.attachment.extension,
                )
                created_file_paths.append(file_path)

                # Check for duplicate file hash in project / ATS
                if file_hash in existing_hashes:
                    storage_service.delete_file(file_path)
                    created_file_paths.pop()
                    fetch_result.skipped.append({
                        "candidate_id": resume.candidate_id,
                        "attachment_id": att_id,
                        "reason": "duplicate content already imported",
                    })
                    fetch_result.already_fetched += 1
                    continue

                existing_hashes.add(file_hash)

                doc_model = DocumentModel(
                    id=doc_id,
                    project_id=project_id,
                    document_type=DocumentTypeEnum.RESUME,
                    original_filename=original_filename,
                    stored_filename=stored_filename,
                    file_path=file_path,
                    file_size_bytes=file_size,
                    file_hash=file_hash,
                    mime_type=resume.content_type,
                    processing_status=ProcessingStatusEnum.UPLOADED,
                    processing_stage=ProcessingStageEnum.INGESTION,
                    metadata_json={
                        "zoho_candidate_id": resume.candidate_id,
                        "zoho_candidate_number": resume.candidate_number,
                        "zoho_attachment_id": att_id,
                        "zoho_job_opening_id": canonical_job_id,
                        "zoho_job_opening_code": opening_code,
                        "zoho_attachment_modified_time": resume.attachment.modified_time,
                        "zoho_candidate_modified_time": resume.modified_time,
                        "candidate_name": resume.full_name,
                        "email": resume.email,
                        "phone": resume.phone,
                        "source": resume.source,
                    },
                    created_at=now,
                    updated_at=now,
                )
                db.add(doc_model)
                saved_document_ids.append(doc_id)

            await db.commit()
        except Exception as exc:
            await db.rollback()
            for fp in created_file_paths:
                storage_service.delete_file(fp)
            logger.exception("zoho_applicants_import_commit_failed", project_id=str(project_id), error=str(exc))
            raise InternalServerException("Unable to persist imported Zoho candidate resumes.") from exc

        # 5. Handle optional auto_process if requested
        if request.auto_process and saved_document_ids:
            try:
                parsing_service = ParsingService(doc_repo, ParsedDocumentRepository(db), storage_service)
                for s_id in saved_document_ids:
                    try:
                        await parsing_service.parse_document(s_id)
                    except Exception as p_exc:
                        logger.warning("zoho_auto_parse_failed", document_id=str(s_id), error=str(p_exc))
            except Exception as auto_exc:
                logger.warning("zoho_auto_process_failed", error=str(auto_exc))

        total_unique_resumes = total_active_resumes_for_job + len(saved_document_ids)
        new_resumes = len(saved_document_ids)
        already_fetched = max(fetch_result.already_fetched, total_active_resumes_for_job)
        failed_resumes = fetch_result.failed_downloads + (len(fetch_result.resumes) - new_resumes)
        total_found = max(fetch_result.total_found, already_fetched + new_resumes + failed_resumes)

        failed_count = failed_resumes or sum(
            1 for s in fetch_result.skipped
            if "fail" in s.get("reason", "").lower() or "error" in s.get("reason", "").lower()
        )

        summary = ZohoFetchSummary(
            total_found=total_found,
            already_fetched=already_fetched,
            new_resumes=new_resumes,
            failed_resumes=failed_resumes,
        )

        return ZohoImportApplicantsResponse(
            project_id=project_id,
            job_id=request.job_id,
            candidates_seen=fetch_result.candidates_seen,
            total_resumes=total_unique_resumes,
            imported_count=new_resumes,
            skipped_count=len(fetch_result.skipped),
            failed_count=failed_count,
            document_ids=saved_document_ids,
            skipped=fetch_result.skipped,
            total_found=total_found,
            already_fetched=already_fetched,
            new_resumes=new_resumes,
            failed_resumes=failed_resumes,
            summary=summary,
        )

