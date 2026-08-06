from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Path, status

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.parsed_document import (
    ParsedDocumentResponse,
    ParseResponseEnvelope,
)
from app.services.parsing_service import ParsingService, run_parsing_task
from app.services.storage_service import StorageService

router = APIRouter()


def get_parsing_service(db: DatabaseDependency) -> ParsingService:
    return ParsingService(
        DocumentRepository(db), ParsedDocumentRepository(db), StorageService()
    )


ParsingServiceDependency = Annotated[ParsingService, Depends(get_parsing_service)]
DocumentId = Annotated[
    UUID, Path(examples=["550e8400-e29b-41d4-a716-446655440000"])
]


@router.post(
    "/{document_id}/parse",
    response_model=ParseResponseEnvelope,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Parse document",
    description="Queue deterministic text extraction and normalization for a document.",
    responses={
        400: {"model": ErrorResponsePayload, "description": "Unsupported format."},
        404: {"model": ErrorResponsePayload, "description": "Document or file missing."},
        422: {"model": ErrorResponsePayload, "description": "Corrupted document."},
    },
)
async def parse_document(
    document_id: DocumentId,
    background_tasks: BackgroundTasks,
    service: ParsingServiceDependency,
) -> ParseResponseEnvelope:
    response, should_schedule = await service.prepare_parsing(document_id)
    if should_schedule:
        background_tasks.add_task(run_parsing_task, document_id)
    return ParseResponseEnvelope(data=response)


@router.get(
    "/{document_id}/parsed",
    response_model=ParsedDocumentResponse,
    summary="Get parsed document",
    description="Retrieve normalized text and parsing metadata for a document.",
    responses={
        404: {
            "model": ErrorResponsePayload,
            "description": "Document or parsed text not found.",
        }
    },
)
async def get_parsed_document(
    document_id: DocumentId, service: ParsingServiceDependency
) -> ParsedDocumentResponse:
    return ParsedDocumentResponse(data=await service.get_parsed_document(document_id))
