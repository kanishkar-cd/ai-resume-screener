from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class ProjectBase(BaseModel):
    title: str = Field(
        ..., min_length=1, max_length=255, examples=["Senior Backend Engineer Campaign"]
    )
    description: str | None = Field(
        None, examples=["Hiring campaign for Q3 senior backend positions."]
    )
    target_role: str = Field(
        ..., min_length=1, max_length=255, examples=["Senior Python Developer"]
    )
    department: str | None = Field(None, max_length=128, examples=["Engineering"])
    status: ProjectStatus = ProjectStatus.DRAFT
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> ProjectStatus:
        if v is None:
            return ProjectStatus.DRAFT
        if isinstance(v, str):
            val = v.strip().upper()
            if val in ProjectStatus.__members__:
                return ProjectStatus[val]
        return v

    @field_validator("metadata_json", mode="before")
    @classmethod
    def validate_metadata_json(cls, v: Any) -> dict[str, Any]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {}

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v: Any) -> str:
        if isinstance(v, str) and v.strip():
            return v.strip()
        return "Untitled Screening Project"

    @field_validator("target_role", mode="before")
    @classmethod
    def validate_target_role(cls, v: Any) -> str:
        if isinstance(v, str) and v.strip():
            return v.strip()
        return "General Role"


class ProjectCreate(ProjectBase):
    """Payload for creating a hiring campaign project."""


class ProjectUpdate(BaseModel):
    """Payload for partially updating a project."""

    title: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = None
    target_role: str | None = Field(None, min_length=2, max_length=255)
    department: str | None = Field(None, max_length=128)
    status: ProjectStatus | None = None
    metadata_json: dict[str, Any] | None = None


class ProjectRead(ProjectBase):
    """Public project representation."""

    id: UUID
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectPaginatedResponse(BaseModel):
    """Paginated project collection."""

    items: list[ProjectRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class ProjectResponse(BaseModel):
    data: ProjectRead


class ProjectListResponse(BaseModel):
    data: ProjectPaginatedResponse
