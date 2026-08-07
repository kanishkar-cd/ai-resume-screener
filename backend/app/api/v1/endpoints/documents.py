from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Path, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentType,
    DocumentUploadResponse,
    ProcessingStatus,
    SortOrder,
)
from app.schemas.error import ErrorResponsePayload
from app.services.document_service import DocumentService
from app.services.storage_service import StorageService

router = APIRouter()

NOT_FOUND_RESPONSE = {
    "model": ErrorResponsePayload,
    "description": "The project, document metadata, or physical file was not found.",
    "content": {
        "application/json": {
            "example": {
                "error": {
                    "code": "DOCUMENT_NOT_FOUND",
                    "message": "The requested document was not found.",
                    "details": {},
                    "timestamp": "2026-08-06T12:00:00Z",
                    "correlation_id": "c3094775-6804-4861-a0c3-04870f2095f9",
                }
            }
        }
    },
}


def get_document_service(db: DatabaseDependency) -> DocumentService:
    """Build the request-scoped document ingestion service."""
    return DocumentService(
        DocumentRepository(db),
        ProjectRepository(db),
        StorageService(),
    )


DocumentServiceDependency = Annotated[
    DocumentService, Depends(get_document_service)
]


@router.post(
    "/upload",
    include_in_schema=False,
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload project document",
    description=(
        "Upload one PDF, DOCX, or TXT resume/job description belonging to an "
        "existing project. Maximum file size is 10 MB."
    ),
    responses={
        400: {"model": ErrorResponsePayload, "description": "Invalid file type."},
        404: NOT_FOUND_RESPONSE,
        409: {"model": ErrorResponsePayload, "description": "Duplicate document."},
        413: {"model": ErrorResponsePayload, "description": "File exceeds 10 MB."},
    },
)
async def upload_document(
    service: DocumentServiceDependency,
    project_id: Annotated[
        UUID,
        Form(
            description="Owning project UUID",
            examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"],
        ),
    ],
    document_type: Annotated[
        DocumentType,
        Form(description="RESUME or JOB_DESCRIPTION", examples=["RESUME"]),
    ],
    file: Annotated[UploadFile, File(description="PDF, DOCX, or TXT document")],
) -> DocumentUploadResponse:
    document = await service.upload_document(project_id, document_type, file)
    return DocumentUploadResponse(data=document)


@router.get(
    "",
    include_in_schema=False,
    response_model=DocumentListResponse,
    summary="List documents",
    description=(
        "List active documents with filename search, Project/type/status filters, "
        "pagination, and created-at sorting."
    ),
    responses={404: NOT_FOUND_RESPONSE},
)
async def list_documents(
    service: DocumentServiceDependency,
    page: Annotated[int, Query(ge=1, examples=[1])] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, examples=[20])] = 20,
    project_id: Annotated[UUID | None, Query(description="Filter by owning project")] = None,
    document_type: Annotated[DocumentType | None, Query()] = None,
    processing_status: Annotated[ProcessingStatus | None, Query()] = None,
    search: Annotated[
        str | None, Query(min_length=1, max_length=255, examples=["resume"])
    ] = None,
    sort_by: Annotated[Literal["created_at"], Query()] = "created_at",
    sort_order: Annotated[SortOrder, Query()] = SortOrder.DESC,
) -> DocumentListResponse:
    del sort_by  # created_at is the only supported sort field in Stage 1.
    documents = await service.list_documents(
        project_id,
        document_type,
        processing_status,
        search,
        page,
        page_size,
        sort_order,
    )
    return DocumentListResponse(data=documents)


@router.get(
    "/{document_id}",
    include_in_schema=False,
    response_model=DocumentResponse,
    summary="Get document metadata",
    description="Retrieve metadata for one active project document.",
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_document(
    document_id: Annotated[UUID, Path(examples=["550e8400-e29b-41d4-a716-446655440000"])],
    service: DocumentServiceDependency,
) -> DocumentResponse:
    return DocumentResponse(data=await service.get_document(document_id))


@router.get(
    "/{document_id}/download",
    include_in_schema=False,
    response_class=FileResponse,
    summary="Download document",
    description="Download the original physical file for an active document.",
    responses={
        200: {
            "description": "Physical document file.",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        },
        404: NOT_FOUND_RESPONSE,
    },
)
async def download_document(
    document_id: Annotated[UUID, Path(examples=["550e8400-e29b-41d4-a716-446655440000"])],
    service: DocumentServiceDependency,
) -> FileResponse:
    download = await service.download_document(document_id)
    return FileResponse(
        path=download.path,
        filename=download.filename,
        media_type=download.mime_type,
    )


@router.delete(
    "/{document_id}",
    include_in_schema=False,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete document",
    description="Soft delete document metadata and remove its physical file.",
    responses={404: NOT_FOUND_RESPONSE},
)
async def delete_document(
    document_id: Annotated[UUID, Path(examples=["550e8400-e29b-41d4-a716-446655440000"])],
    service: DocumentServiceDependency,
) -> Response:
    await service.delete_document(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
