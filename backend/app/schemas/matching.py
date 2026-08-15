from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Any


class RequirementKind(str, Enum):
    SKILL = "skill"
    DEGREE = "degree"
    CERTIFICATION = "certification"
    LANGUAGE = "language"
    HARD_CONSTRAINT = "hard_constraint"
    PROJECT_RELEVANCE = "project_relevance"
    RESPONSIBILITY = "responsibility"
    CONTEXTUAL_EXPERIENCE = "contextual_experience"


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    NO_MATCH = "NO_MATCH"
    UNRESOLVED = "UNRESOLVED"


class MatchMethod(str, Enum):
    EXACT = "exact"
    ALIAS = "alias"
    TAXONOMY = "taxonomy"
    LLM_CONFIRMED = "llm_confirmed"
    LLM_REJECTED = "llm_rejected"
    LLM_UNRESOLVED = "llm_unresolved"


class Requirement(BaseModel):
    requirement_id: str = Field(min_length=1)
    kind: RequirementKind
    text: str = Field(min_length=1)
    canonical_value: str | None = None
    required: bool = True
    hard_constraint: bool = False


class Evidence(BaseModel):
    evidence_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    text: str = Field(min_length=1)
    canonical_terms: list[str] = Field(default_factory=list)


class MatchVerdict(BaseModel):
    requirement_id: str = Field(min_length=1)
    status: MatchStatus
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""
    method: MatchMethod | None = None

    @model_validator(mode="after")
    def validate_method(self) -> "MatchVerdict":
        if self.status == MatchStatus.MATCHED and self.method is None:
            raise ValueError("matched verdicts require a method")
        if self.method == MatchMethod.LLM_CONFIRMED and self.status != MatchStatus.MATCHED:
            raise ValueError("llm_confirmed is valid only for matched verdicts")
        if self.method == MatchMethod.LLM_REJECTED and self.status != MatchStatus.NO_MATCH:
            raise ValueError("llm_rejected is valid only for no_match verdicts")
        if self.method == MatchMethod.LLM_UNRESOLVED and self.status != MatchStatus.UNRESOLVED:
            raise ValueError("llm_unresolved is valid only for unresolved verdicts")
        return self


class LLMVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str = Field(min_length=1)
    status: MatchStatus
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""


class LLMVerdictBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdicts: list[LLMVerdict] = Field(default_factory=list)


class CandidateMatchingProfile(BaseModel):
    candidate_name: str | None = None
    email: str | None = None
    phone: str | None = None
    resume_job_title: str | None = None
    jd_job_title: str | None = None
    total_experience_months: int = 0
    candidate_level: str = "FRESHER"
    jd_required_level: str = "FRESHER"
    education: list[dict[str, Any]] = Field(default_factory=list)


class ResponsibilityMatchDetail(BaseModel):
    responsibility: str
    status: MatchStatus
    confidence: float
    evidence_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""
    method: MatchMethod | None = None


class NormalizedMatchResult(BaseModel):
    profile: CandidateMatchingProfile
    required_skills_score: float = Field(ge=0, le=100)
    responsibility_score: float = Field(ge=0, le=100)
    preferred_skills_score: float = Field(ge=0, le=100)
    job_title_score: float = Field(ge=0, le=100)
    relevant_experience_score: float | None = None
    final_match_score: float = Field(default=0.0, ge=0, le=100)
    matched_required_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    matched_preferred_skills: list[str] = Field(default_factory=list)
    missing_preferred_skills: list[str] = Field(default_factory=list)
    responsibility_details: list[ResponsibilityMatchDetail] = Field(default_factory=list)
    short_relevance_explanation: str = ""
