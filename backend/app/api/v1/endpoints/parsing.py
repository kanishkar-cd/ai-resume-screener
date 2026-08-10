from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.parsed_document import DocumentParseResponse, ParsedDocumentResponse
from app.services.parsing_service import ParsingService
from app.services.storage_service import StorageService

router = APIRouter()

NOT_FOUND_RESPONSE = {
    "model": ErrorResponsePayload,
    "description": "The document or parsed result was not found.",
}


def get_parsing_service(db: DatabaseDependency) -> ParsingService:
    """Build the request-scoped document parsing service."""
    return ParsingService(
        DocumentRepository(db),
        ParsedDocumentRepository(db),
        StorageService(),
    )


ParsingServiceDependency = Annotated[ParsingService, Depends(get_parsing_service)]


@router.post(
    "/{document_id}/parse",
    response_model=DocumentParseResponse,
    status_code=status.HTTP_200_OK,
    summary="Parse document",
    description=(
        "Extract text from an uploaded PDF, DOCX, or TXT document. "
        "Advances processing status UPLOADED → PARSING_PENDING → PARSED or FAILED."
    ),
    responses={
        404: NOT_FOUND_RESPONSE,
        409: {
            "model": ErrorResponsePayload,
            "description": "Document is not in a parseable status.",
        },
        422: {
            "model": ErrorResponsePayload,
            "description": "Document parsing failed.",
        },
    },
)
async def parse_document(
    document_id: Annotated[
        UUID, Path(examples=["550e8400-e29b-41d4-a716-446655440000"])
    ],
    service: ParsingServiceDependency,
) -> DocumentParseResponse:
    return DocumentParseResponse(data=await service.parse_document(document_id))


@router.get(
    "/{document_id}/parsed",
    response_model=ParsedDocumentResponse,
    summary="Get parsed document",
    description="Return the persisted parse result for a document.",
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_parsed_document(
    document_id: Annotated[
        UUID, Path(examples=["550e8400-e29b-41d4-a716-446655440000"])
    ],
    service: ParsingServiceDependency,
) -> ParsedDocumentResponse:
    return ParsedDocumentResponse(data=await service.get_parsed_document(document_id))
