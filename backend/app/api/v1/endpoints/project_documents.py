from datetime import UTC, datetime
from pathlib import Path as FilePath
from time import perf_counter
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Path, Query, Response, UploadFile, status
from sqlalchemy import or_, select
import structlog

from app.api.deps import DatabaseDependency
from app.api.v1.endpoints.documents import get_document_service
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
    BatchResumeUploadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    JobDescriptionProcessRead,
    JobDescriptionProcessResponse,
    ProcessingStage,
    ProcessingStatus,
    SortOrder,
)
from app.schemas.error import ErrorResponsePayload
from app.schemas.extracted_jd import ExtractedJDRead
from app.schemas.normalized_jd import NormalizedJDRead
from app.services.document_service import (
    DocumentService,
    DuplicateDocumentException,
    InternalServerException,
)
from app.services.jd_extraction_service import JDExtractionService
from app.services.jd_normalization_service import JDNormalizationService
from app.services.parsing_service import ParsingService
from app.services.project_service import ProjectNotFoundException
from app.services.storage_service import StorageService
from app.utils.file_validation import validate_file

logger = structlog.get_logger(__name__)

router = APIRouter()

DocumentServiceDependency = Annotated[DocumentService, Depends(get_document_service)]
ProjectId = Annotated[
    UUID, Path(examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])
]


@router.post(
    "/projects/{project_id}/job-description",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload or replace Job Description",
    description="Attach exactly one active Job Description to a project.",
    responses={
        400: {"model": ErrorResponsePayload, "description": "Invalid file."},
        404: {"model": ErrorResponsePayload, "description": "Project not found."},
        409: {"model": ErrorResponsePayload, "description": "Duplicate document."},
        413: {"model": ErrorResponsePayload, "description": "File too large."},
    },
)
async def upload_job_description(
    project_id: ProjectId,
    service: DocumentServiceDependency,
    file: Annotated[
        UploadFile, File(description="One PDF, DOCX, or TXT Job Description")
    ],
) -> DocumentUploadResponse:
    return DocumentUploadResponse(
        data=await service.upload_job_description(project_id, file)
    )


@router.post(
    "/projects/{project_id}/job-description/process",
    response_model=JobDescriptionProcessResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload and process Job Description end-to-end",
    description=(
        "Upload a Job Description and run the complete pipeline: "
        "Upload -> Parse -> Extract -> Normalize in a single unified backend flow."
    ),
    responses={
        400: {"model": ErrorResponsePayload, "description": "Invalid file."},
        404: {"model": ErrorResponsePayload, "description": "Project not found."},
        409: {"model": ErrorResponsePayload, "description": "Duplicate document."},
        413: {"model": ErrorResponsePayload, "description": "File too large."},
        422: {"model": ErrorResponsePayload, "description": "Processing failed."},
    },
)
async def process_job_description(
    project_id: ProjectId,
    file: Annotated[
        UploadFile, File(description="One PDF, DOCX, or TXT Job Description")
    ],
    db: DatabaseDependency,
) -> JobDescriptionProcessResponse:
    t_process_start = perf_counter()
    logger.info(
        "[PROCESS_JD_START] Starting optimized in-memory JD processing",
        project_id=str(project_id),
        filename=file.filename,
    )

    # 1. Verify project (Round Trip 1: 1 SELECT)
    t0 = perf_counter()
    proj_repo = ProjectRepository(db)
    project = await proj_repo.get_by_id(project_id)
    if project is None:
        raise ProjectNotFoundException()
    t_verify = (perf_counter() - t0) * 1000
    logger.info("[PROCESS_JD_TIMING] Project verified", duration_ms=round(t_verify, 2))

    # 2. File validation & disk write (0 DB calls)
    t0 = perf_counter()
    original_filename, extension = await validate_file(file)
    storage_service = StorageService()
    stored_filename, file_path, size, file_hash = await storage_service.save_file(
        file, project_id, "job_description", extension
    )
    t_file_save = (perf_counter() - t0) * 1000
    logger.info("[PROCESS_JD_TIMING] File validated and saved to disk", duration_ms=round(t_file_save, 2))

    # 3. Duplicate check and soft-delete prior active JD in one query (Round Trip 2: 1 SELECT)
    t0 = perf_counter()
    existing_stmt = select(DocumentModel).where(
        DocumentModel.project_id == project_id,
        DocumentModel.deleted_at.is_(None),
        or_(
            DocumentModel.file_hash == file_hash,
            DocumentModel.document_type == DocumentTypeEnum.JOB_DESCRIPTION,
        ),
    )
    existing_records = (await db.scalars(existing_stmt)).all()
    prior_jd_record = None
    for rec in existing_records:
        if rec.file_hash == file_hash:
            storage_service.delete_file(file_path)
            raise DuplicateDocumentException()
        if rec.document_type == DocumentTypeEnum.JOB_DESCRIPTION:
            prior_jd_record = rec

    now = datetime.now(UTC)
    if prior_jd_record is not None:
        prior_jd_record.deleted_at = now
    t_check = (perf_counter() - t0) * 1000
    logger.info("[PROCESS_JD_TIMING] Duplicate check & prior JD mark-delete query", duration_ms=round(t_check, 2))

    # 4. In-memory DocumentModel instantiation (0 DB calls)
    doc_id = uuid4()
    doc_model = DocumentModel(
        id=doc_id,
        project_id=project_id,
        document_type=DocumentTypeEnum.JOB_DESCRIPTION,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_path=file_path,
        file_size_bytes=size,
        mime_type=file.content_type or "application/octet-stream",
        file_hash=file_hash,
        processing_stage=ProcessingStageEnum.COMPLETED,
        processing_status=ProcessingStatusEnum.COMPLETED,
        created_at=now,
        updated_at=now,
    )
    db.add(doc_model)

    # 5. Local PyMuPDF Parse in worker thread (0 DB calls)
    t0 = perf_counter()
    doc_repo = DocumentRepository(db)
    parsed_repo = ParsedDocumentRepository(db)
    parsing_service = ParsingService(doc_repo, parsed_repo, storage_service)
    parsed_output, word_count, character_count, parse_duration_ms = await parsing_service.parse_local_file(
        FilePath(file_path), doc_model.mime_type
    )
    t_parse = (perf_counter() - t0) * 1000
    logger.info("[PROCESS_JD_TIMING] Local parse finished", duration_ms=round(t_parse, 2))

    parsed_id = uuid4()
    parsed_model = ParsedDocumentModel(
        id=parsed_id,
        document_id=doc_id,
        raw_text=parsed_output.raw_text,
        normalized_text=parsed_output.raw_text,
        page_count=parsed_output.page_count,
        word_count=word_count,
        character_count=character_count,
        parser_engine=parsed_output.parser_engine.value,
        parsing_duration_ms=round(parse_duration_ms, 3),
        created_at=now,
        updated_at=now,
    )
    db.add(parsed_model)

    # 6. In-memory Extraction (0 DB calls)
    t0 = perf_counter()
    extracted_repo = ExtractedJDRepository(db)
    jd_extract_service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
    extracted_create = await jd_extract_service.extract_from_raw_text(
        raw_text=parsed_output.raw_text,
        document_id=doc_id,
        source_word_count=word_count,
    )
    t_extract = (perf_counter() - t0) * 1000
    logger.info("[PROCESS_JD_TIMING] In-memory extract finished", duration_ms=round(t_extract, 2))

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

    # 7. In-memory Normalization (0 DB calls)
    t0 = perf_counter()
    normalized_repo = NormalizedJDRepository(db)
    jd_norm_service = JDNormalizationService(doc_repo, extracted_repo, normalized_repo)
    normalized_create = jd_norm_service.normalize_from_extracted(
        extracted=extracted_create,
        document_id=doc_id,
        extracted_id=extracted_id,
    )
    t_norm = (perf_counter() - t0) * 1000
    logger.info("[PROCESS_JD_TIMING] In-memory normalize finished", duration_ms=round(t_norm, 2))

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

    # 8. Single Atomic DB Commit (Round Trip 3: 1 COMMIT)
    t0 = perf_counter()
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        storage_service.delete_file(file_path)
        logger.exception("jd_unified_db_commit_failed", document_id=str(doc_id), error=str(exc))
        raise InternalServerException("Unable to persist Job Description pipeline results.") from exc
    t_commit = (perf_counter() - t0) * 1000
    logger.info("[PROCESS_JD_TIMING] Single atomic DB commit finished", duration_ms=round(t_commit, 2))

    if prior_jd_record is not None:
        try:
            storage_service.delete_file(prior_jd_record.file_path)
        except Exception:
            logger.exception("prior_jd_file_cleanup_failed", document_id=str(prior_jd_record.id))

    # 9. Build response directly from memory (0 DB calls)
    t0 = perf_counter()
    extracted_read = ExtractedJDRead(
        id=extracted_id,
        document_id=doc_id,
        created_at=now,
        updated_at=now,
        **extracted_create.model_dump(exclude={"document_id"}),
    )
    normalized_read = NormalizedJDRead(
        id=normalized_id,
        document_id=doc_id,
        extracted_job_description_id=extracted_id,
        created_at=now,
        updated_at=now,
        **normalized_create.model_dump(exclude={"document_id", "extracted_job_description_id"}),
    )
    response_obj = JobDescriptionProcessResponse(
        data=JobDescriptionProcessRead(
            document_id=doc_id,
            project_id=project_id,
            filename=original_filename,
            processing_stage=ProcessingStage.COMPLETED,
            processing_status=ProcessingStatus.COMPLETED,
            extracted=extracted_read.model_dump(mode="json"),
            normalized=normalized_read.model_dump(mode="json"),
        )
    )
    t_resp_build = (perf_counter() - t0) * 1000

    t_total = (perf_counter() - t_process_start) * 1000
    logger.info(
        "[PROCESS_JD_TIMING_SUMMARY] Total breakdown for POST /projects/{project_id}/job-description/process",
        document_id=str(doc_id),
        total_duration_ms=round(t_total, 2),
        verify_project_ms=round(t_verify, 2),
        file_save_ms=round(t_file_save, 2),
        duplicate_check_ms=round(t_check, 2),
        parse_ms=round(t_parse, 2),
        extract_ms=round(t_extract, 2),
        normalize_ms=round(t_norm, 2),
        atomic_commit_ms=round(t_commit, 2),
        resp_build_ms=round(t_resp_build, 2),
    )

    return response_obj


@router.get(
    "/projects/{project_id}/job-description",
    response_model=DocumentResponse,
    summary="Get project Job Description",
    description="Retrieve the single active Job Description attached to a project.",
    responses={404: {"model": ErrorResponsePayload, "description": "Not found."}},
)
async def get_job_description(
    project_id: ProjectId, service: DocumentServiceDependency
) -> DocumentResponse:
    return DocumentResponse(data=await service.get_job_description(project_id))


@router.post(
    "/projects/{project_id}/resumes/batch",
    response_model=BatchResumeUploadResponse,
    status_code=status.HTTP_207_MULTI_STATUS,
    summary="Upload resume batch",
    description=(
        "Upload up to 50 resume files. Each file is validated independently; "
        "the aggregate request limit is 100 MB."
    ),
    responses={
        404: {"model": ErrorResponsePayload, "description": "Project not found."},
        413: {"model": ErrorResponsePayload, "description": "Batch limit exceeded."},
    },
)
async def upload_resume_batch(
    project_id: ProjectId,
    service: DocumentServiceDependency,
    files: Annotated[
        list[UploadFile],
        File(description="Multiple PDF, DOCX, or TXT candidate resumes"),
    ],
) -> BatchResumeUploadResponse:
    return BatchResumeUploadResponse(
        data=await service.upload_resume_batch(project_id, files)
    )


@router.get(
    "/projects/{project_id}/resumes",
    response_model=DocumentListResponse,
    summary="List project resumes",
    description="List active resumes scoped to one project.",
    responses={404: {"model": ErrorResponsePayload, "description": "Project not found."}},
)
async def list_project_resumes(
    project_id: ProjectId,
    service: DocumentServiceDependency,
    page: Annotated[int, Query(ge=1, examples=[1])] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, examples=[20])] = 20,
    processing_status: Annotated[ProcessingStatus | None, Query()] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    sort_order: Annotated[SortOrder, Query()] = SortOrder.DESC,
) -> DocumentListResponse:
    return DocumentListResponse(
        data=await service.list_project_resumes(
            project_id,
            processing_status,
            search,
            page,
            page_size,
            sort_order,
        )
    )


@router.delete(
    "/projects/{project_id}/resumes/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a resume from a project",
    description=(
        "Delete one uploaded candidate resume and cascade clean up all "
        "downstream parsed, extracted, normalized, scoring, ranking, and AI insight records."
    ),
    responses={
        400: {"model": ErrorResponsePayload, "description": "Document does not belong to project."},
        404: {"model": ErrorResponsePayload, "description": "Project or document not found."},
    },
)
async def delete_resume(
    project_id: ProjectId,
    document_id: Annotated[UUID, Path(description="Resume document ID")],
    service: DocumentServiceDependency,
) -> Response:
    await service.delete_resume(project_id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/projects/{project_id}/job-description",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete active Job Description",
    description=(
        "Delete the project's active Job Description and cascade clean up "
        "all downstream parsed, extracted, and normalized job description records."
    ),
    responses={
        404: {"model": ErrorResponsePayload, "description": "Project or Job Description not found."},
    },
)
async def delete_job_description(
    project_id: ProjectId,
    service: DocumentServiceDependency,
) -> Response:
    await service.delete_job_description(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
