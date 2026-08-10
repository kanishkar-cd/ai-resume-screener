from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.extracted_jd_repository import ExtractedJDRepository
from app.repositories.normalized_jd_repository import NormalizedJDRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.extracted_jd import ExtractedJDResponse, JDExtractResponse
from app.schemas.normalized_jd import JDNormalizeResponse, NormalizedJDResponse
from app.services.jd_extraction_service import JDExtractionService
from app.services.jd_normalization_service import JDNormalizationService

router = APIRouter()

_DOC_ID_PATH = Path(examples=["550e8400-e29b-41d4-a716-446655440000"])
_404 = {"model": ErrorResponsePayload, "description": "Document or result not found."}
_409 = {"model": ErrorResponsePayload, "description": "Document is not in an extractable state."}


# ─── Dependency factories ────────────────────────────────────────────────────

def get_extraction_service(db: DatabaseDependency) -> JDExtractionService:
    return JDExtractionService(
        DocumentRepository(db),
        ParsedDocumentRepository(db),
        ExtractedJDRepository(db),
    )


def get_normalization_service(db: DatabaseDependency) -> JDNormalizationService:
    return JDNormalizationService(
        DocumentRepository(db),
        ExtractedJDRepository(db),
        NormalizedJDRepository(db),
    )


ExtractionServiceDep = Annotated[JDExtractionService, Depends(get_extraction_service)]
NormalizationServiceDep = Annotated[JDNormalizationService, Depends(get_normalization_service)]


# ─── Extract endpoints ───────────────────────────────────────────────────────

@router.post(
    "/{document_id}/extract",
    response_model=JDExtractResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract JD fields",
    description=(
        "Run heuristic extraction on a parsed JD document to produce structured fields: "
        "skills, responsibilities, education, experience, certifications, keywords, domain."
    ),
    responses={404: _404, 409: _409},
)
async def extract_document(
    document_id: Annotated[UUID, _DOC_ID_PATH],
    service: ExtractionServiceDep,
) -> JDExtractResponse:
    result = await service.extract_document(document_id)
    return JDExtractResponse(data=result)


@router.get(
    "/{document_id}/extracted",
    response_model=ExtractedJDResponse,
    summary="Get extracted JD",
    description="Return the persisted extraction result for a JD document.",
    responses={404: _404},
)
async def get_extracted_document(
    document_id: Annotated[UUID, _DOC_ID_PATH],
    service: ExtractionServiceDep,
) -> ExtractedJDResponse:
    result = await service.get_extracted_document(document_id)
    return ExtractedJDResponse(data=result)


# ─── Normalize endpoints ─────────────────────────────────────────────────────

@router.post(
    "/{document_id}/normalize",
    response_model=JDNormalizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Normalize extracted JD",
    description=(
        "Produce a canonical, deduplicated requirement set from an extracted JD. "
        "Normalizes skills (lowercase/sort), degrees (canonical names), "
        "experience (min/max months), and keywords."
    ),
    responses={404: _404, 409: _409},
)
async def normalize_document(
    document_id: Annotated[UUID, _DOC_ID_PATH],
    service: NormalizationServiceDep,
) -> JDNormalizeResponse:
    result = await service.normalize_document(document_id)
    return JDNormalizeResponse(data=result)


@router.get(
    "/{document_id}/normalized",
    response_model=NormalizedJDResponse,
    summary="Get normalized JD",
    description="Return the persisted normalization result for a JD document.",
    responses={404: _404},
)
async def get_normalized_document(
    document_id: Annotated[UUID, _DOC_ID_PATH],
    service: NormalizationServiceDep,
) -> NormalizedJDResponse:
    result = await service.get_normalized_document(document_id)
    return NormalizedJDResponse(data=result)
