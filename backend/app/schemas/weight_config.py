from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WeightDistribution(BaseModel):
    required_skills: float = Field(default=50.0, ge=0.0, le=100.0)
    responsibilities: float = Field(default=50.0, ge=0.0, le=100.0)
    preferred_skills: float = Field(default=0.0, ge=0.0, le=100.0)
    skills: float | None = None
    experience: float = 0.0
    projects: float = 0.0
    education: float = 0.0
    certifications: float = 0.0
    languages: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "skills" in data and "required_skills" not in data:
                data["required_skills"] = data["skills"]
        return data


class KnockoutRule(BaseModel):
    rule_type: str
    enabled: bool = True
    description: str | None = None


class WeightConfigCreate(BaseModel):
    weights: WeightDistribution | dict[str, float] = Field(default_factory=WeightDistribution)
    passing_score: float = Field(default=70.0, ge=0.0, le=100.0)
    min_experience_years: float = Field(default=0.0, ge=0.0, le=50.0)
    required_degree: str | None = None
    required_certifications: list[str] = Field(default_factory=list)
    mandatory_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    knockout_rules: list[KnockoutRule | dict[str, Any]] = Field(default_factory=list)
    custom_keywords: list[str] = Field(default_factory=list)


class WeightConfigUpdate(BaseModel):
    weights: WeightDistribution | dict[str, float] | None = None
    passing_score: float | None = Field(default=None, ge=0.0, le=100.0)
    min_experience_years: float | None = Field(default=None, ge=0.0, le=50.0)
    required_degree: str | None = None
    required_certifications: list[str] | None = None
    mandatory_skills: list[str] | None = None
    preferred_skills: list[str] | None = None
    knockout_rules: list[KnockoutRule | dict[str, Any]] | None = None
    custom_keywords: list[str] | None = None


class WeightConfigRead(BaseModel):
    id: UUID
    project_id: UUID
    weights: dict[str, float] | WeightDistribution
    passing_score: float
    min_experience_years: float
    required_degree: str | None
    required_certifications: list[str]
    mandatory_skills: list[str]
    preferred_skills: list[str]
    knockout_rules: list[dict[str, Any]]
    custom_keywords: list[str]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WeightConfigResponse(BaseModel):
    data: WeightConfigRead
