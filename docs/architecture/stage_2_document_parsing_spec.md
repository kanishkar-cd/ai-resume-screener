# Stage 2 Architecture Specification: Document Parsing Subsystem

**Project**: `ai-resume-screener`  
**Subsystem**: Stage 2 – Document Parsing Subsystem  
**Target Stack**: Python 3.12, FastAPI, SQLAlchemy 2.0 (Async), Alembic, PostgreSQL, Pydantic v2  
**Role**: Principal Software Architect  
**Status**: Approved Technical Specification for Codex Implementation  

---

## Executive Overview

Stage 2 defines the **Document Parsing Subsystem**. It transforms raw binary document files ingested in Stage 1 (`.pdf`, `.docx`, `.txt`) into clean, normalized text and structured extraction metadata required for downstream AI processing.

### Core Capabilities
* **Format-Specific Extraction**: Extracts raw text and page counts from PDF, DOCX, and TXT files.
* **Text Normalization**: Strips control characters, normalizes line breaks (`\n`), and collapses excessive whitespace.
* **Metadata Extraction**: Calculates word count, character count, page count, parsing latency, and detects document language.
* **Status State Machine**: Updates document `processing_stage` (`PARSING`) and `processing_status` (`IN_PROGRESS` -> `COMPLETED` / `FAILED`).
* **Storage Isolation**: Persists normalized text and metadata in a dedicated `parsed_documents` PostgreSQL table linked to `documents`.

### Strict Scope Exclusions
* **NO** OCR (Optical Character Recognition).
* **NO** LLMs or generative AI.
* **NO** Embeddings or vector database ingestion.
* **NO** Text chunking or splitting.
* **NO** Skill, experience, education, or entity extraction.
* **NO** Candidate scoring, ranking, or job matching.

---

## 1. Subsystem Architecture

```text
Physical File (storage/uploads/) 
       │
       ▼
[Parser Factory] ──► Selects Parser (PDFParser / DocxParser / TxtParser)
       │
       ▼
[Text Extraction Engine] ──► Extracts Raw Text & Page Count
       │
       ▼
[Normalization Pipeline] ──► Cleans Whitespace, Control Chars, Language Detect
       │
       ▼
[Repository Layer] ──► Persists to PostgreSQL `parsed_documents` table
       │
       ▼
[Status State Machine] ──► Updates `documents.processing_stage = 'PARSED'`
```

---

## 2. Database Schema Changes

### 2.1 Schema Migration (`parsed_documents` Table)

```sql
-- Extend processing state enums
ALTER TYPE processing_status_enum ADD VALUE IF NOT EXISTS 'IN_PROGRESS';
ALTER TYPE processing_status_enum ADD VALUE IF NOT EXISTS 'COMPLETED';

CREATE TABLE parsed_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    page_count INTEGER NULL,
    word_count INTEGER NOT NULL,
    character_count INTEGER NOT NULL,
    language VARCHAR(16) NULL,
    parser_engine VARCHAR(64) NOT NULL,
    parsing_duration_ms DOUBLE PRECISION NOT NULL,
    parsing_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Performance & Query Optimization Indexes
CREATE INDEX ix_parsed_documents_document_id ON parsed_documents(document_id);
CREATE INDEX ix_parsed_documents_language ON parsed_documents(language);
CREATE INDEX ix_parsed_documents_parser_engine ON parsed_documents(parser_engine);
```

### 2.2 Table Updates (`documents` Table)
Add tracking fields to `documents` table:
```sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_stage VARCHAR(32) NOT NULL DEFAULT 'INGESTION';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT NULL;
```

---

## 3. SQLAlchemy Model (`app/models/parsed_document.py`)

Inherits from `Base`, `UUIDMixin`, and `TimestampMixin`.

```text
app/models/parsed_document.py
└── ParsedDocumentModel (SQLAlchemy 2.0 Declarative Table)
    ├── id: Mapped[uuid.UUID] (UUIDMixin Primary Key)
    ├── document_id: Mapped[uuid.UUID] (ForeignKey("documents.id", ondelete="CASCADE"), unique=True)
    ├── raw_text: Mapped[str] (Text, nullable=False)
    ├── normalized_text: Mapped[str] (Text, nullable=False)
    ├── page_count: Mapped[Optional[int]] (Integer, nullable=True)
    ├── word_count: Mapped[int] (Integer, nullable=False)
    ├── character_count: Mapped[int] (Integer, nullable=False)
    ├── language: Mapped[Optional[str]] (String(16), nullable=True)
    ├── parser_engine: Mapped[str] (String(64), nullable=False)
    ├── parsing_duration_ms: Mapped[float] (Float, nullable=False)
    ├── parsing_metadata: Mapped[dict] (JSONB, nullable=False, default={})
    ├── created_at: Mapped[datetime] (TimestampMixin, UTC)
    └── updated_at: Mapped[datetime] (TimestampMixin, UTC)
```

---

## 4. Pydantic Schemas (`app/schemas/parsed_document.py`)

```python
# Enums
class ParserEngineEnum(str, Enum):
    PYMUPDF = "PYMUPDF"
    PYTHON_DOCX = "PYTHON_DOCX"
    PLAIN_TEXT = "PLAIN_TEXT"

# Schemas
class ParsedDocumentBase(BaseModel):
    page_count: Optional[int] = None
    word_count: int
    character_count: int
    language: Optional[str] = "en"
    parser_engine: ParserEngineEnum
    parsing_duration_ms: float

class ParsedDocumentCreate(ParsedDocumentBase):
    document_id: UUID4
    raw_text: str
    normalized_text: str
    parsing_metadata: dict[str, Any] = {}

class ParsedDocumentRead(ParsedDocumentBase):
    id: UUID4
    document_id: UUID4
    normalized_text: str
    parsing_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ParseDocumentResponse(BaseModel):
    document_id: UUID4
    status: ProcessingStatus
    processing_stage: str = "PARSED"
    message: str
```

---

## 5. Repository Responsibilities (`app/repositories/parsed_document_repository.py`)

The `ParsedDocumentRepository` manages persistence for parsed text entities:

* **`create_or_update(parsed_data: ParsedDocumentCreate) -> ParsedDocumentModel`**: Upserts parsed document entity linked to `document_id`.
* **`get_by_document_id(document_id: UUID4) -> Optional[ParsedDocumentModel]`**: Fetches parsed document text and metadata by `document_id`.
* **`delete_by_document_id(document_id: UUID4) -> bool`**: Removes parsed record upon document deletion.

---

## 6. Service Responsibilities (`app/services/parsing_service.py`)

The `ParsingService` orchestrates the parsing lifecycle:

* **Parser Routing**: Inspects document `mime_type` and selects matching parser engine.
* **Pipeline Execution**: Invokes raw extraction and normalization pipeline.
* **Status Updates**: Updates parent `DocumentModel` status (`IN_PROGRESS` -> `COMPLETED` / `FAILED`).
* **Idempotent Execution**: Can be called directly by HTTP handlers or asynchronously via background workers.

---

## 7. Text Normalization Pipeline (`app/services/pipeline/normalization_pipeline.py`)

A deterministic 4-stage pipeline processes extracted raw text:

```text
Raw Extracted Text
       │
       ▼
[Step 1: Line Break Standardization] ──► Convert \r\n to \n
       │
       ▼
[Step 2: Control Char Strip] ──► Remove non-printable control chars (\x00-\x08, \x0b, \x0c, \x0e-\x1f)
       │
       ▼
[Step 3: Whitespace Compression] ──► Reduce multiple horizontal spaces to single space per line
       │
       ▼
[Step 4: Paragraph Separation] ──► Collapse 3+ consecutive newlines to maximum 2 newlines (\n\n)
       │
       ▼
Normalized Clean Text Output
```

### Language Detection & Metadata Computation
* `character_count`: `len(normalized_text)`
* `word_count`: `len(normalized_text.split())`
* `language`: Detected using lightweight `langdetect` library (falls back to `"en"` if ambiguous).

---

## 8. Supported Parsers (`app/services/parsers/`)

* **`PDFParser` (`app/services/parsers/pdf_parser.py`)**: Uses `PyMuPDF` (`fitz`) to extract clean text page-by-page. Returns page count and combined text string.
* **`DocxParser` (`app/services/parsers/docx_parser.py`)**: Uses `python-docx` to iterate through paragraphs and table cells.
* **`TxtParser` (`app/services/parsers/txt_parser.py`)**: UTF-8 plain text file reader.

---

## 9. Error Handling & Custom Exceptions

Mapped to `app.core.exceptions.AppException`:

| Exception Class | HTTP Code | Error Code String | Trigger Scenario |
| :--- | :---: | :--- | :--- |
| `UnsupportedFormatException` | 400 | `UNSUPPORTED_PARSER_FORMAT` | File mime type has no registered parser |
| `DocumentParsingException` | 500 | `PARSING_EXECUTION_FAILED` | Internal parser library error during extraction |
| `CorruptedFileException` | 422 | `CORRUPTED_DOCUMENT_FILE` | PDF/DOCX structure corrupted or unreadable |
| `ParsedDocumentNotFoundException` | 404 | `PARSED_DOCUMENT_NOT_FOUND` | Document has not yet been parsed |

---

## 10. API Contracts (`app/api/v1/endpoints/parsing.py`)

### 10.1 `POST /api/v1/documents/{document_id}/parse`
* **Description**: Trigger parsing pipeline for an uploaded document.
* **Response (HTTP 200 OK / 202 Accepted)**:
```json
{
  "data": {
    "document_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "COMPLETED",
    "processing_stage": "PARSED",
    "message": "Document parsed successfully."
  }
}
```

### 10.2 `GET /api/v1/documents/{document_id}/parsed`
* **Description**: Retrieve extracted normalized text and metadata.
* **Response (HTTP 200 OK)**:
```json
{
  "data": {
    "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "document_id": "550e8400-e29b-41d4-a716-446655440000",
    "normalized_text": "John Doe\nSenior Python Engineer...\nExperience:\n- Built FastAPI microservices...",
    "page_count": 2,
    "word_count": 450,
    "character_count": 2890,
    "language": "en",
    "parser_engine": "PYMUPDF",
    "parsing_duration_ms": 42.5,
    "parsing_metadata": {
      "pdf_version": "1.7",
      "is_encrypted": false
    },
    "created_at": "2026-08-06T14:30:00Z",
    "updated_at": "2026-08-06T14:30:00Z"
  }
}
```

---

## 11. Background Processing Strategy

* **Execution Paths**:
  1. **Synchronous/FastAPI BackgroundTasks**: Immediately processes small document parsing jobs (<5MB) in non-blocking background threads (`BackgroundTasks`).
  2. **Celery/Redis Compatibility**: `ParsingService.parse_document(document_id)` is strictly idempotent, enabling seamless conversion into Celery worker tasks in Stage 7/8.

---

## 12. Testing Strategy

### 12.1 Unit Tests (`tests/unit/`)
* `test_normalization_pipeline.py`: Test control character stripping, newline collapsing, and whitespace normalization.
* `test_pdf_parser.py`, `test_docx_parser.py`, `test_txt_parser.py`: Test raw text and page count extraction using sample mock files.

### 12.2 Integration Tests (`tests/integration/`)
* `test_parsed_document_repository.py`: Test upserting and fetching `ParsedDocumentModel` in PostgreSQL.

### 12.3 E2E Endpoint Tests (`tests/e2e/`)
* `test_parsing_api.py`: Test `POST /api/v1/documents/{document_id}/parse` and `GET /api/v1/documents/{document_id}/parsed` via `httpx.AsyncClient`.

---

## 13. File Manifest for Codex Implementation

### Files to Create
```text
backend/app/models/parsed_document.py
backend/app/schemas/parsed_document.py
backend/app/repositories/parsed_document_repository.py
backend/app/services/parsing_service.py
backend/app/services/parsers/base_parser.py
backend/app/services/parsers/pdf_parser.py
backend/app/services/parsers/docx_parser.py
backend/app/services/parsers/txt_parser.py
backend/app/services/pipeline/normalization_pipeline.py
backend/app/api/v1/endpoints/parsing.py
backend/alembic/versions/<timestamp>_create_parsed_documents_table.py
tests/unit/test_parsers.py
tests/unit/test_normalization_pipeline.py
tests/integration/test_parsed_document_repository.py
tests/e2e/test_parsing_api.py
```

### Files to Modify
```text
backend/app/models/__init__.py        # Export ParsedDocumentModel
backend/app/api/v1/router.py          # Mount parsing.py endpoint router
backend/requirements.txt              # Add pymupdf, python-docx, langdetect
```
