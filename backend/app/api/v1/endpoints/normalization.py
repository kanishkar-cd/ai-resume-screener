from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.normalized_info import NormalizedDocumentResponse, NormalizeResponseEnvelope
from app.services.normalization_service import NormalizationService

router = APIRouter()


def get_normalization_service(db: DatabaseDependency) -> NormalizationService:
    return NormalizationService(DocumentRepository(db), ExtractionRepository(db), NormalizationRepository(db))


NormalizationServiceDependency = Annotated[NormalizationService, Depends(get_normalization_service)]
DocumentId = Annotated[UUID, Path(examples=["550e8400-e29b-41d4-a716-446655440000"])]


@router.post(
    "/{document_id}/normalize", response_model=NormalizeResponseEnvelope,
    status_code=status.HTTP_200_OK, summary="Normalize document data",
    description="Apply the versioned deterministic Stage 4 ruleset to Stage 3 structured data.",
    responses={
        400: {"model": ErrorResponsePayload, "description": "Stage 3 extracted data is unavailable."},
        404: {"model": ErrorResponsePayload, "description": "Document not found."},
        422: {"model": ErrorResponsePayload, "description": "Unsupported type or canonical validation failure."},
        500: {"model": ErrorResponsePayload, "description": "Normalization failed."},
    },
)
async def normalize_document(document_id: DocumentId, service: NormalizationServiceDependency) -> NormalizeResponseEnvelope:
    return NormalizeResponseEnvelope(data=await service.normalize_document_data(document_id))


@router.get(
    "/{document_id}/normalized", response_model=NormalizedDocumentResponse,
    summary="Get normalized document data",
    description="Retrieve persisted canonical data, ruleset version, audit changes, warnings, and confidence.",
    responses={
        404: {"model": ErrorResponsePayload, "description": "Document or normalized data not found."},
        422: {"model": ErrorResponsePayload, "description": "Unsupported document type."},
    },
)
async def get_normalized_document(document_id: DocumentId, service: NormalizationServiceDependency) -> NormalizedDocumentResponse:
    return NormalizedDocumentResponse(data=await service.get_normalized_data(document_id))
