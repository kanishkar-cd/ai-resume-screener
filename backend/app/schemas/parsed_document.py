from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.document import ProcessingStage, ProcessingStatus


class ParserEngineEnum(str, Enum):
    PYMUPDF = "PYMUPDF"
    PYTHON_DOCX = "PYTHON_DOCX"
    PLAIN_TEXT = "PLAIN_TEXT"


class ParsedDocumentBase(BaseModel):
    page_count: int | None = Field(None, ge=0)
    word_count: int = Field(ge=0)
    character_count: int = Field(ge=0)
    language: str | None = "en"
    parser_engine: ParserEngineEnum
    parsing_duration_ms: float = Field(ge=0)


class ParsedDocumentCreate(ParsedDocumentBase):
    document_id: UUID
    raw_text: str
    normalized_text: str
    parsing_metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedDocumentRead(ParsedDocumentBase):
    id: UUID
    document_id: UUID
    normalized_text: str
    parsing_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ParseDocumentResponse(BaseModel):
    document_id: UUID
    status: ProcessingStatus
    processing_stage: ProcessingStage
    message: str


class ParseResponseEnvelope(BaseModel):
    data: ParseDocumentResponse


class ParsedDocumentResponse(BaseModel):
    data: ParsedDocumentRead
