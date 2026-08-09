from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WeightDistribution(BaseModel):
    skills: int = Field(default=40, ge=0, le=100)
    experience: int = Field(default=25, ge=0, le=100)
    projects: int = Field(default=15, ge=0, le=100)
    education: int = Field(default=10, ge=0, le=100)
    certifications: int = Field(default=5, ge=0, le=100)
    languages: int = Field(default=5, ge=0, le=100)

    @model_validator(mode="after")
    def validate_total_weight(self) -> "WeightDistribution":
        total = (
            self.skills
            + self.experience
            + self.projects
            + self.education
            + self.certifications
            + self.languages
        )
        if total != 100:
            raise ValueError(
                f"Total criterion weight distribution must equal 100% (got {total}%)."
            )
        return self


class KnockoutRule(BaseModel):
    rule_type: str
    enabled: bool = True
    description: str | None = None


class WeightConfigCreate(BaseModel):
    weights: WeightDistribution = Field(default_factory=WeightDistribution)
    passing_score: float = Field(default=60.0, ge=0.0, le=100.0)
    min_experience_years: float = Field(default=0.0, ge=0.0)
    required_degree: str | None = None
    required_certifications: list[str] = Field(default_factory=list)
    mandatory_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    knockout_rules: list[KnockoutRule] = Field(default_factory=list)
    custom_keywords: list[str] = Field(default_factory=list)


class WeightConfigUpdate(BaseModel):
    weights: WeightDistribution | None = None
    passing_score: float | None = Field(default=None, ge=0.0, le=100.0)
    min_experience_years: float | None = Field(default=None, ge=0.0)
    required_degree: str | None = None
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
