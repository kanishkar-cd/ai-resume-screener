from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.extracted_jd_repository import ExtractedJDRepository
from app.repositories.normalized_jd_repository import NormalizedJDRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.models.document import DocumentTypeEnum
from app.schemas.error import ErrorResponsePayload
from app.schemas.extracted_info import ExtractDocumentResponse, ExtractResponseEnvelope, ExtractedDocumentResponse
from app.schemas.extracted_jd import ExtractedJDResponse, JDExtractResponse
from app.schemas.normalized_jd import JDNormalizeResponse, NormalizedJDResponse
from app.services.document_service import DocumentNotFoundException
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


from app.repositories.extraction_repository import ExtractionRepository
from app.services.extraction_service import ExtractionService


def get_general_extraction_service(db: DatabaseDependency) -> ExtractionService:
    return ExtractionService(
        DocumentRepository(db),
        ParsedDocumentRepository(db),
        ExtractionRepository(db),
    )


GeneralExtractionServiceDep = Annotated[ExtractionService, Depends(get_general_extraction_service)]


# ─── Extract endpoints ───────────────────────────────────────────────────────

@router.post(
    "/{document_id}/extract",
    response_model=JDExtractResponse | ExtractResponseEnvelope,
    status_code=status.HTTP_200_OK,
    summary="Extract document fields",
    description=(
        "Run heuristic extraction on a parsed document (Resume or Job Description) "
        "to produce structured fields."
    ),
    responses={404: _404, 409: _409},
)
async def extract_document(
    document_id: Annotated[UUID, _DOC_ID_PATH],
    jd_service: ExtractionServiceDep,
    general_service: GeneralExtractionServiceDep,
    db: DatabaseDependency,
) -> JDExtractResponse | ExtractResponseEnvelope:
    doc_repo = DocumentRepository(db)
    document = await doc_repo.get_by_id(document_id)
    if document is None:
        raise DocumentNotFoundException()
    if document.document_type == DocumentTypeEnum.RESUME:
        result = await general_service.extract_document_data(document_id)
        return ExtractResponseEnvelope(data=result)
    result = await jd_service.extract_document(document_id)
    return JDExtractResponse(data=result)


@router.get(
    "/{document_id}/extracted",
    response_model=ExtractedJDResponse | ExtractedDocumentResponse,
    summary="Get extracted document",
    description="Return the persisted extraction result for a Resume or JD document.",
    responses={404: _404},
)
async def get_extracted_document(
    document_id: Annotated[UUID, _DOC_ID_PATH],
    jd_service: ExtractionServiceDep,
    general_service: GeneralExtractionServiceDep,
    db: DatabaseDependency,
) -> ExtractedJDResponse | ExtractedDocumentResponse:
    doc_repo = DocumentRepository(db)
    document = await doc_repo.get_by_id(document_id)
    if document is None:
        raise DocumentNotFoundException()
    if document.document_type == DocumentTypeEnum.RESUME:
        data = await general_service.get_extracted_data(document_id)
        return ExtractedDocumentResponse(data=data)
    result = await jd_service.get_extracted_document(document_id)
    return ExtractedJDResponse(data=result)


from app.repositories.normalization_repository import NormalizationRepository
from app.schemas.normalized_info import NormalizeResponseEnvelope, NormalizedDocumentResponse
from app.services.normalization_service import NormalizationService


def get_general_normalization_service(db: DatabaseDependency) -> NormalizationService:
    return NormalizationService(
        DocumentRepository(db),
        ExtractionRepository(db),
        NormalizationRepository(db),
    )


GeneralNormalizationServiceDep = Annotated[NormalizationService, Depends(get_general_normalization_service)]


# ─── Normalize endpoints ─────────────────────────────────────────────────────

@router.post(
    "/{document_id}/normalize",
    response_model=JDNormalizeResponse | NormalizeResponseEnvelope,
    status_code=status.HTTP_200_OK,
    summary="Normalize extracted document",
    description=(
        "Produce a canonical, deduplicated requirement/profile set from an extracted document "
        "(Resume or Job Description)."
    ),
    responses={404: _404, 409: _409},
)
async def normalize_document(
    document_id: Annotated[UUID, _DOC_ID_PATH],
    jd_service: NormalizationServiceDep,
    general_service: GeneralNormalizationServiceDep,
    db: DatabaseDependency,
) -> JDNormalizeResponse | NormalizeResponseEnvelope:
    doc_repo = DocumentRepository(db)
    document = await doc_repo.get_by_id(document_id)
    if document is None:
        raise DocumentNotFoundException()
    if document.document_type == DocumentTypeEnum.RESUME:
        result = await general_service.normalize_document_data(document_id)
        return NormalizeResponseEnvelope(data=result)
    result = await jd_service.normalize_document(document_id)
    return JDNormalizeResponse(data=result)


@router.get(
    "/{document_id}/normalized",
    response_model=NormalizedJDResponse | NormalizedDocumentResponse,
    summary="Get normalized document",
    description="Return the persisted normalization result for a Resume or JD document.",
    responses={404: _404},
)
async def get_normalized_document(
    document_id: Annotated[UUID, _DOC_ID_PATH],
    jd_service: NormalizationServiceDep,
    general_service: GeneralNormalizationServiceDep,
    db: DatabaseDependency,
) -> NormalizedJDResponse | NormalizedDocumentResponse:
    doc_repo = DocumentRepository(db)
    document = await doc_repo.get_by_id(document_id)
    if document is None:
        raise DocumentNotFoundException()
    if document.document_type == DocumentTypeEnum.RESUME:
        data = await general_service.get_normalized_data(document_id)
        return NormalizedDocumentResponse(data=data)
    result = await jd_service.get_normalized_document(document_id)
    return NormalizedJDResponse(data=result)
