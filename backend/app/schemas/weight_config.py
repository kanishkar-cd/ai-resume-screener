from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WeightDistribution(BaseModel):
    skills: float = Field(40.0, ge=0, le=100)
    experience: float = Field(25.0, ge=0, le=100)
    projects: float = Field(15.0, ge=0, le=100)
    education: float = Field(10.0, ge=0, le=100)
    certifications: float = Field(5.0, ge=0, le=100)
    languages: float = Field(5.0, ge=0, le=100)



class KnockoutRule(BaseModel):
    rule_type: str = Field(min_length=1, max_length=64, examples=["MISSING_MANDATORY_SKILL"])
    enabled: bool = True
    description: str | None = Field(default=None, max_length=500)


class SkillListValidationMixin(BaseModel):
    pass


class WeightConfigCreate(SkillListValidationMixin):
    weights: WeightDistribution = Field(default_factory=WeightDistribution)
    passing_score: float = Field(70.0, ge=0, le=100)
    min_experience_years: float = Field(0.0, ge=0, le=50)
    required_degree: str | None = Field(default=None, max_length=255)
    required_certifications: list[str] = Field(default_factory=list)
    mandatory_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    knockout_rules: list[KnockoutRule] = Field(default_factory=list)
    custom_keywords: list[str] = Field(default_factory=list)


class WeightConfigUpdate(SkillListValidationMixin):
    weights: WeightDistribution | None = None
    passing_score: float | None = Field(default=None, ge=0, le=100)
    min_experience_years: float | None = Field(default=None, ge=0, le=50)
    required_degree: str | None = Field(default=None, max_length=255)
    required_certifications: list[str] | None = None
    mandatory_skills: list[str] | None = None
    preferred_skills: list[str] | None = None
    knockout_rules: list[KnockoutRule] | None = None
    custom_keywords: list[str] | None = None


class WeightConfigRead(BaseModel):
    id: UUID
    project_id: UUID
    weights: WeightDistribution
    passing_score: float
    min_experience_years: float
    required_degree: str | None
    required_certifications: list[str]
    mandatory_skills: list[str]
    preferred_skills: list[str]
    knockout_rules: list[KnockoutRule]
    custom_keywords: list[str]
    version: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WeightConfigResponse(BaseModel):
    data: WeightConfigRead
