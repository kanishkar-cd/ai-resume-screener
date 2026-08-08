from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.document import ProcessingStage, ProcessingStatus


class ParserEngine(str, Enum):
    PYMUPDF = "PYMUPDF"
    PYTHON_DOCX = "PYTHON_DOCX"
    PLAIN_TEXT = "PLAIN_TEXT"


class ParsedDocumentCreate(BaseModel):
    document_id: UUID
    raw_text: str
    page_count: int | None = None
    word_count: int = Field(ge=0)
    character_count: int = Field(ge=0)
    parser_engine: ParserEngine
    parsing_duration_ms: float = Field(ge=0)


class DocumentParseRead(BaseModel):
    document_id: UUID
    processing_status: ProcessingStatus
    processing_stage: ProcessingStage
    message: str
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
                "processing_status": "PARSED",
                "processing_stage": "UPLOAD",
                "message": "Document parsed successfully.",
            }
        }
    )


class DocumentParseResponse(BaseModel):
    data: DocumentParseRead


class ParsedDocumentRead(BaseModel):
    id: UUID
    document_id: UUID
    raw_text: str
    page_count: int | None
    word_count: int
    character_count: int
    parser_engine: ParserEngine
    parsing_duration_ms: float
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
                "raw_text": "Senior Python engineer with FastAPI experience.",
                "page_count": 1,
                "word_count": 6,
                "character_count": 48,
                "parser_engine": "PLAIN_TEXT",
                "parsing_duration_ms": 12.5,
                "created_at": "2026-08-08T12:00:00Z",
                "updated_at": "2026-08-08T12:00:00Z",
            }
        },
    )


class ParsedDocumentResponse(BaseModel):
    data: ParsedDocumentRead
