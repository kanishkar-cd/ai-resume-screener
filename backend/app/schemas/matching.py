from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequirementKind(str, Enum):
    SKILL = "skill"
    REQUIRED_SKILL = "required_skill"
    PREFERRED_SKILL = "preferred_skill"
    DEGREE = "degree"
    CERTIFICATION = "certification"
    LANGUAGE = "language"
    HARD_CONSTRAINT = "hard_constraint"
    PROJECT_RELEVANCE = "project_relevance"
    RESPONSIBILITY = "responsibility"
    CONTEXTUAL_EXPERIENCE = "contextual_experience"
    EXPERIENCE = "experience"
    CANDIDATE_ATTRIBUTE = "candidate_attribute"
    SCREENING_NOTE = "screening_note"


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    NO_MATCH = "NO_MATCH"
    UNMATCHED = "UNMATCHED"
    UNRESOLVED = "UNRESOLVED"
    EVALUATION_FAILED = "EVALUATION_FAILED"


class MatchMethod(str, Enum):
    EXACT = "exact"
    ALIAS = "alias"
    TAXONOMY = "taxonomy"
    LLM_CONFIRMED = "llm_confirmed"
    LLM_REJECTED = "llm_rejected"
    LLM_UNRESOLVED = "llm_unresolved"
    EVALUATION_FAILED = "evaluation_failed"


class Requirement(BaseModel):
    requirement_id: str = Field(min_length=1)
    kind: RequirementKind
    text: str = Field(min_length=1)
    canonical_value: str | None = None
    required: bool = True
    hard_constraint: bool = False
    importance: str = "important"
    importance_reasoning: str | None = None
    is_likely_boilerplate: bool = False


class Evidence(BaseModel):
    evidence_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    text: str = Field(min_length=1)
    canonical_terms: list[str] = Field(default_factory=list)


class MatchVerdict(BaseModel):
    requirement_id: str = Field(min_length=1)
    requirement_text: str | None = None
    kind: RequirementKind | None = None
    status: MatchStatus
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""
    method: MatchMethod | None = None
    coverage: float = Field(default=1.0, ge=0, le=1)
    coverage_score: float = Field(default=1.0, ge=0, le=1)
    importance: str = Field(default="important")
    sub_claims: list[str] = Field(default_factory=list)
    sub_claim_evidence: list[dict[str, Any]] = Field(default_factory=list)
    matched_concepts: list[str] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_method(self) -> "MatchVerdict":
        # Keep coverage and coverage_score synchronized
        if self.coverage_score is not None and self.coverage == 1.0 and self.coverage_score != 1.0:
            self.coverage = self.coverage_score
        elif self.coverage is not None and self.coverage != 1.0 and self.coverage_score == 1.0:
            self.coverage_score = self.coverage

        if self.status in {MatchStatus.MATCHED, MatchStatus.PARTIALLY_MATCHED} and self.method is None:
            raise ValueError("Method is required for matched verdicts")
        if self.method == MatchMethod.LLM_CONFIRMED and self.status not in {MatchStatus.MATCHED, MatchStatus.PARTIALLY_MATCHED}:
            raise ValueError("llm_confirmed is valid only for matched verdicts")
        if self.method == MatchMethod.LLM_REJECTED and self.status not in {MatchStatus.NO_MATCH, MatchStatus.UNMATCHED}:
            raise ValueError("llm_rejected is valid only for no_match verdicts")
        if self.method == MatchMethod.LLM_UNRESOLVED and self.status != MatchStatus.UNRESOLVED:
            raise ValueError("llm_unresolved is valid only for unresolved verdicts")
        if self.method == MatchMethod.EVALUATION_FAILED and self.status != MatchStatus.EVALUATION_FAILED:
            raise ValueError("evaluation_failed method is valid only for evaluation_failed status")
        return self


class LLMVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    requirement_id: str = Field(min_length=1)
    status: MatchStatus | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""
    coverage: float | None = None
    coverage_score: float | None = None
    importance: str = Field(default="important")
    sub_claims: list[str] = Field(default_factory=list)
    sub_claim_evidence: list[dict[str, Any]] = Field(default_factory=list)
    matched_concepts: list[str] | None = None
    missing_concepts: list[str] | None = None


class LLMVerdictBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdicts: list[LLMVerdict] = Field(default_factory=list)


LLMVerdictItem = LLMVerdict
