from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Path, Query, Response, UploadFile, status

from app.api.v1.endpoints.documents import get_document_service
from app.schemas.document import (
    BatchResumeUploadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    ProcessingStatus,
    SortOrder,
)
from app.schemas.error import ErrorResponsePayload
from app.services.document_service import DocumentService

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
