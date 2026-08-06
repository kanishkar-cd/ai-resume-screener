from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.extracted_info import (
    ExtractedDocumentResponse,
    ExtractResponseEnvelope,
)
from app.services.extraction_service import ExtractionService

router = APIRouter()


def get_extraction_service(db: DatabaseDependency) -> ExtractionService:
    return ExtractionService(
        DocumentRepository(db), ParsedDocumentRepository(db), ExtractionRepository(db)
    )


ExtractionServiceDependency = Annotated[ExtractionService, Depends(get_extraction_service)]
DocumentId = Annotated[UUID, Path(examples=["550e8400-e29b-41d4-a716-446655440000"])]


@router.post(
    "/{document_id}/extract",
    response_model=ExtractResponseEnvelope,
    status_code=status.HTTP_200_OK,
    summary="Extract document information",
    description="Extract structured resume or job-description fields from Stage 2 normalized text.",
    responses={
        400: {"model": ErrorResponsePayload, "description": "Parsed text is unavailable."},
        404: {"model": ErrorResponsePayload, "description": "Document not found."},
        500: {"model": ErrorResponsePayload, "description": "Extraction pipeline failed."},
    },
)
async def extract_document(
    document_id: DocumentId, service: ExtractionServiceDependency
) -> ExtractResponseEnvelope:
    return ExtractResponseEnvelope(data=await service.extract_document_data(document_id))


@router.get(
    "/{document_id}/extracted",
    response_model=ExtractedDocumentResponse,
    summary="Get extracted document information",
    description="Retrieve persisted structured data and per-field confidence scores.",
    responses={
        404: {"model": ErrorResponsePayload, "description": "Document or extracted data not found."}
    },
)
async def get_extracted_document(
    document_id: DocumentId, service: ExtractionServiceDependency
) -> ExtractedDocumentResponse:
    return ExtractedDocumentResponse(data=await service.get_extracted_data(document_id))
