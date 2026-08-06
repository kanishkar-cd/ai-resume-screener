# Stage 1 Architecture Specification: Project Module

**Project**: `ai-resume-screener`  
**Subsystem**: Stage 1 – Project Campaign Module  
**Target Stack**: Python 3.12, FastAPI, SQLAlchemy 2.0 (Async), Alembic, PostgreSQL, Pydantic v2  
**Role**: Principal Software Architect  
**Status**: Approved Technical Specification for Codex Implementation  

---

## Executive Overview

The **Project Module** defines the foundational entity for organizing hiring campaigns within `ai-resume-screener`. 

A **Project** encapsulates an individual hiring campaign (e.g., "Senior Python Engineer Q3 Hiring"). In future stages, each Project will serve as the parent aggregate container linking:
* Exactly **One Job Description Document**
* **Multiple Resume Documents**
* Candidate match evaluation results, AI scoring parameters, and analytics.

---

## 1. Database Schema (`projects` Table)

```sql
CREATE TYPE project_status_enum AS ENUM ('DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED');

CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    target_role VARCHAR(255) NOT NULL,
    department VARCHAR(128) NULL,
    status project_status_enum NOT NULL DEFAULT 'DRAFT',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ NULL
);

-- Performance & Indexing Optimization
CREATE INDEX ix_projects_status ON projects(status);
CREATE INDEX ix_projects_target_role ON projects(target_role);
CREATE INDEX ix_projects_created_at ON projects(created_at DESC);
```

---

## 2. SQLAlchemy Model Fields (`app/models/project.py`)

Inherits from `Base`, `UUIDMixin`, and `TimestampMixin` defined in `app.db`.

```text
app/models/project.py
└── ProjectModel (SQLAlchemy 2.0 Declarative Table)
    ├── id: Mapped[uuid.UUID] (UUIDMixin Primary Key)
    ├── title: Mapped[str] (String(255), nullable=False)
    ├── description: Mapped[Optional[str]] (Text, nullable=True)
    ├── target_role: Mapped[str] (String(255), nullable=False)
    ├── department: Mapped[Optional[str]] (String(128), nullable=True)
    ├── status: Mapped[ProjectStatusEnum] (Enum(ProjectStatusEnum), nullable=False, default=DRAFT)
    ├── metadata_json: Mapped[dict] (JSONB, nullable=False, default={})
    ├── created_at: Mapped[datetime] (TimestampMixin, UTC)
    ├── updated_at: Mapped[datetime] (TimestampMixin, UTC)
    └── deleted_at: Mapped[Optional[datetime]] (TIMESTAMPTZ, nullable=True)
```

---

## 3. Pydantic Schemas (`app/schemas/project.py`)

```python
# Enums
class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"

# Core Schemas
class ProjectBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=255, example="Senior Backend Engineer Campaign")
    description: Optional[str] = Field(None, example="Hiring campaign for Q3 senior backend positions.")
    target_role: str = Field(..., min_length=2, max_length=255, example="Senior Python Developer")
    department: Optional[str] = Field(None, max_length=128, example="Engineering")
    status: ProjectStatus = Field(default=ProjectStatus.DRAFT)
    metadata_json: dict[str, Any] = Field(default_factory=dict)

class ProjectCreate(ProjectBase):
    """Schema for POST /api/v1/projects request payload."""
    pass

class ProjectUpdate(BaseModel):
    """Schema for PATCH /api/v1/projects/{project_id} partial updates."""
    title: Optional[str] = Field(None, min_length=3, max_length=255)
    description: Optional[str] = None
    target_role: Optional[str] = Field(None, min_length=2, max_length=255)
    department: Optional[str] = Field(None, max_length=128)
    status: Optional[ProjectStatus] = None
    metadata_json: Optional[dict[str, Any]] = None

class ProjectRead(ProjectBase):
    """Schema for project responses."""
    id: UUID4
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ProjectPaginatedResponse(BaseModel):
    """Paginated list response wrapper."""
    items: list[ProjectRead]
    total: int
    page: int
    page_size: int
    total_pages: int
```

---

## 4. Repository Responsibilities (`app/repositories/project_repository.py`)

The `ProjectRepository` isolates raw database interactions using `AsyncSession`:

* **`create(project_in: ProjectCreate) -> ProjectModel`**: Instantiates and persists a new project entity.
* **`get_by_id(project_id: UUID4) -> Optional[ProjectModel]`**: Fetches an active (non-soft-deleted) project by ID.
* **`list_projects(status: Optional[ProjectStatus], search: Optional[str], page: int, page_size: int) -> tuple[list[ProjectModel], int]`**: Queries paginated project records with optional status filtering and title/target_role search.
* **`update(project_id: UUID4, update_data: ProjectUpdate) -> Optional[ProjectModel]`**: Applies partial field updates to an existing project entity.
* **`soft_delete(project_id: UUID4) -> bool`**: Sets `deleted_at = NOW()` for soft deletion.

---

## 5. Service Responsibilities (`app/services/project_service.py`)

The `ProjectService` manages business rules and domain validations:

* **Domain Validation**:
  - Enforces project title and target_role sanitization.
  - Validates status transition constraints (e.g., `ARCHIVED` projects cannot transition back to `DRAFT` without explicit reactivation).
* **Exception Translation**:
  - Catches database errors and raises standard domain exceptions (`ProjectNotFoundException`, `DuplicateProjectException`).
* **Service Methods**:
  - `create_project(payload: ProjectCreate) -> ProjectRead`
  - `get_project(project_id: UUID4) -> ProjectRead`
  - `list_projects(status, search, page, page_size) -> ProjectPaginatedResponse`
  - `update_project(project_id: UUID4, payload: ProjectUpdate) -> ProjectRead`
  - `delete_project(project_id: UUID4) -> bool`

---

## 6. REST API Contracts (`app/api/v1/endpoints/projects.py`)

All endpoints are registered under `/api/v1/projects`.

### 6.1 `POST /api/v1/projects`
* **Description**: Create a new hiring campaign project.
* **Request Body**: `ProjectCreate`
* **Response (HTTP 201 Created)**:
```json
{
  "data": {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "title": "Senior Backend Engineer Campaign",
    "description": "Hiring campaign for Q3 senior backend positions.",
    "target_role": "Senior Python Developer",
    "department": "Engineering",
    "status": "DRAFT",
    "metadata_json": {},
    "created_at": "2026-08-06T12:25:00Z",
    "updated_at": "2026-08-06T12:25:00Z"
  }
}
```

### 6.2 `GET /api/v1/projects`
* **Description**: List projects with pagination and status filtering.
* **Query Parameters**:
  - `page` (int, default=1)
  - `page_size` (int, default=20, max=100)
  - `status` (optional `ProjectStatus` enum)
  - `search` (optional string search in `title` or `target_role`)
* **Response (HTTP 200 OK)**:
```json
{
  "data": {
    "items": [
      {
        "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "title": "Senior Backend Engineer Campaign",
        "description": "Hiring campaign for Q3 senior backend positions.",
        "target_role": "Senior Python Developer",
        "department": "Engineering",
        "status": "DRAFT",
        "metadata_json": {},
        "created_at": "2026-08-06T12:25:00Z",
        "updated_at": "2026-08-06T12:25:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20,
    "total_pages": 1
  }
}
```

### 6.3 `GET /api/v1/projects/{project_id}`
* **Description**: Retrieve details of a specific project.
* **Response (HTTP 200 OK)**: Returns `ProjectRead` DTO.
* **Error (HTTP 404 Not Found)**: Returns standard `PROJECT_NOT_FOUND` error payload.

### 6.4 `PATCH /api/v1/projects/{project_id}`
* **Description**: Partially update an existing project's metadata or status.
* **Request Body**: `ProjectUpdate`
* **Response (HTTP 200 OK)**: Returns updated `ProjectRead` DTO.

### 6.5 `DELETE /api/v1/projects/{project_id}`
* **Description**: Soft delete a hiring campaign project.
* **Response (HTTP 204 No Content)**: Returns empty response body upon successful deletion.

---

## 7. File Manifest for Codex Implementation

### Files to Create
```text
backend/app/models/project.py
backend/app/schemas/project.py
backend/app/repositories/project_repository.py
backend/app/services/project_service.py
backend/app/api/v1/endpoints/projects.py
backend/alembic/versions/<timestamp>_create_projects_table.py
tests/unit/test_project_service.py
tests/integration/test_project_repository.py
tests/e2e/test_projects_api.py
```

### Files to Modify
```text
backend/app/models/__init__.py    # Export ProjectModel
backend/app/api/v1/router.py      # Mount projects.py endpoint router
```
