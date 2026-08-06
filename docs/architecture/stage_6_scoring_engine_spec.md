# Stage 6 Architecture Specification: Candidate Scoring Engine

**Project**: `ai-resume-screener`  
**Subsystem**: Stage 6 – Multi-Engine Candidate Scoring & Decision Subsystem  
**Target Stack**: Python 3.12, FastAPI, SQLAlchemy 2.0 (Async), Alembic, PostgreSQL, Pydantic v2  
**Role**: Principal Software Architect  
**Status**: Approved Technical Specification for Codex Implementation  

---

## Executive Overview

Stage 6 introduces the **Multi-Engine Candidate Scoring & Decision Subsystem**. It evaluates candidate resume documents against job requirements and recruiter weight configurations to produce objective component scores and weighted final hiring recommendations.

The subsystem consists of two decoupled internal scoring engines:
* **ENGINE A: Component Scoring Engine**: Evaluates candidates objectively and independently to produce raw, unweighted 0–100 component scores.
* **ENGINE B: Final Decision & Scoring Engine**: Applies recruiter weight configurations, mandatory rules, knockout rules, penalties, bonuses, and confidence metrics to generate final scores and recommendation classifications.

### Strict Scope Exclusions
* **NO** candidate ranking or candidate sorting (Stage 7 concern).
* **NO** LLMs or generative AI explanations.
* **NO** Embeddings or vector similarity searches.
* **NO** UI dashboard rendering or export generators.

---

## 1. Subsystem Architecture & Dual Engine Flow

```mermaid
flowchart TD
    subgraph Data Inputs
        R[Extracted Candidate Resume Data]
        J[Extracted Job Description Data]
        W[Recruiter Weight Configuration]
    end

    subgraph ENGINE A: Component Scoring Engine
        A1[Skills Matcher] --> CS[Raw Component Scores 0-100]
        A2[Experience Evaluator] --> CS
        A3[Projects Evaluator] --> CS
        A4[Education Evaluator] --> CS
        A5[Certifications Evaluator] --> CS
        A6[Languages Evaluator] --> CS
    end

    subgraph ENGINE B: Final Decision & Scoring Engine
        CS & W --> B1[Apply Recruiter Weights]
        B1 --> B2[Knockout & Mandatory Rule Check]
        B2 -->|Pass| B3[Apply Penalties & Bonuses]
        B2 -->|Fail| B4[Flag DISQUALIFIED]
        B3 --> B5[Compute Final Score & Confidence]
        B4 & B5 --> B6[Generate Recommendation Level]
    end

    R & J --> ENGINE A
    ENGINE A --> ENGINE B
    ENGINE B --> DB[(PostgreSQL candidate_scores)]
```

---

## 2. Database Schema (`candidate_scores` Table)

```sql
CREATE TYPE recommendation_level_enum AS ENUM (
    'STRONG_MATCH', 
    'RECOMMENDED', 
    'NEEDS_REVIEW', 
    'NOT_RECOMMENDED'
);

CREATE TABLE candidate_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    
    -- Engine A Output: Raw Component Breakdown
    component_scores JSONB NOT NULL,
    
    -- Engine B Output: Weighted & Adjusted Results
    raw_total_score NUMERIC(5,2) NOT NULL,
    weighted_total_score NUMERIC(5,2) NOT NULL,
    penalty_total NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    bonus_total NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    final_score NUMERIC(5,2) NOT NULL,
    confidence NUMERIC(5,2) NOT NULL,
    recommendation recommendation_level_enum NOT NULL,
    
    -- Knockout & Rule Summary
    is_knocked_out BOOLEAN NOT NULL DEFAULT FALSE,
    knockout_reason TEXT NULL,
    penalty_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
    bonus_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Performance Indexes
CREATE INDEX ix_candidate_scores_document_id ON candidate_scores(document_id);
CREATE INDEX ix_candidate_scores_project_id ON candidate_scores(project_id);
CREATE INDEX ix_candidate_scores_recommendation ON candidate_scores(recommendation);
```

---

## 3. SQLAlchemy Model (`app/models/scoring.py`)

Inherits from `Base`, `UUIDMixin`, and `TimestampMixin`.

```text
app/models/scoring.py
└── CandidateScoreModel (SQLAlchemy 2.0 Declarative Table)
    ├── id: Mapped[uuid.UUID] (UUIDMixin Primary Key)
    ├── document_id: Mapped[uuid.UUID] (ForeignKey("documents.id", ondelete="CASCADE"), unique=True)
    ├── project_id: Mapped[uuid.UUID] (ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    ├── component_scores: Mapped[dict] (JSONB, nullable=False)
    ├── raw_total_score: Mapped[float] (Numeric(5,2), nullable=False)
    ├── weighted_total_score: Mapped[float] (Numeric(5,2), nullable=False)
    ├── penalty_total: Mapped[float] (Numeric(5,2), default=0.0)
    ├── bonus_total: Mapped[float] (Numeric(5,2), default=0.0)
    ├── final_score: Mapped[float] (Numeric(5,2), nullable=False)
    ├── confidence: Mapped[float] (Numeric(5,2), nullable=False)
    ├── recommendation: Mapped[RecommendationLevelEnum] (Enum, nullable=False)
    ├── is_knocked_out: Mapped[bool] (Boolean, default=False)
    ├── knockout_reason: Mapped[Optional[str]] (Text, nullable=True)
    ├── penalty_summary: Mapped[list] (JSONB, default=[])
    ├── bonus_summary: Mapped[list] (JSONB, default=[])
    ├── created_at: Mapped[datetime] (TimestampMixin, UTC)
    └── updated_at: Mapped[datetime] (TimestampMixin, UTC)
```

---

## 4. Pydantic Schemas (`app/schemas/scoring.py`)

```python
class RecommendationLevel(str, Enum):
    STRONG_MATCH = "STRONG_MATCH"
    RECOMMENDED = "RECOMMENDED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"

class ComponentScoreDetail(BaseModel):
    score: float = Field(..., ge=0.0, le=100.0)
    matched_items: list[str] = []
    missing_items: list[str] = []
    explanation: str

class ComponentScores(BaseModel):
    skills: ComponentScoreDetail
    experience: ComponentScoreDetail
    projects: ComponentScoreDetail
    education: ComponentScoreDetail
    certifications: ComponentScoreDetail
    languages: ComponentScoreDetail

class AdjustmentItem(BaseModel):
    rule_name: str
    delta_points: float
    description: str

class CandidateScoreRead(BaseModel):
    id: UUID4
    document_id: UUID4
    project_id: UUID4
    component_scores: ComponentScores
    raw_total_score: float
    weighted_total_score: float
    penalty_total: float
    bonus_total: float
    final_score: float
    confidence: float
    recommendation: RecommendationLevel
    is_knocked_out: bool
    knockout_reason: Optional[str] = None
    penalty_summary: list[AdjustmentItem] = []
    bonus_summary: list[AdjustmentItem] = []
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ProjectScoringResponse(BaseModel):
    project_id: UUID4
    total_evaluated: int
    scores: list[CandidateScoreRead]
```

---

## 5. Repository & Service Responsibilities

### 5.1 Repository Layer (`app/repositories/scoring_repository.py`)
* `create_or_update(score_data: dict) -> CandidateScoreModel`
* `get_by_document_id(document_id: UUID4) -> Optional[CandidateScoreModel]`
* `list_by_project_id(project_id: UUID4) -> list[CandidateScoreModel]`

### 5.2 Service Layer (`app/services/scoring_service.py`)
* **`ComponentScoringService` (`app/services/scoring/component_scoring_service.py`)**: Implements Engine A logic.
* **`FinalDecisionService` (`app/services/scoring/final_decision_service.py`)**: Implements Engine B logic.
* **`ScoringEngineFacade` (`app/services/scoring_service.py`)**: Orchestrates data loading from Stage 3 (`extracted_resumes`, `extracted_job_descriptions`) and Stage 5 (`project_weight_configs`), executes Engine A & B, and persists scores.

---

## 6. Engine A: Component Scoring Pipeline

Evaluates candidate attributes against job specifications independently (0–100 scale):

1. **Skills Component Score**:
   $$S_{\text{skills}} = \min\left(100, \frac{|\text{MatchedSkills}|}{|\text{RequiredSkills}|} \times 100\right)$$
2. **Experience Component Score**:
   $$S_{\text{exp}} = \min\left(100, \frac{\text{CandidateYears}}{\text{RequiredYears}} \times 100\right)$$
3. **Education Component Score**:
   $$S_{\text{edu}} = 100 \text{ if candidate degree } \ge \text{ required degree, else } 50$$
4. **Projects Component Score**: Match project technology tags against job keywords.
5. **Certifications Component Score**: Percentage of required certifications matched.
6. **Languages Component Score**: Percentage of required languages matched.

---

## 7. Engine B: Final Decision & Scoring Pipeline

1. **Knockout Rule Check**:
   - Check if candidate lacks mandatory skills or required experience.
   - If triggered: `is_knocked_out = True`, `recommendation = NOT_RECOMMENDED`, `final_score = 0.0`.
2. **Weighted Score Calculation**:
   $$\text{WeightedScore} = \sum_{i \in \{\text{skills, exp, proj, edu, cert, lang}\}} S_i \times \frac{W_i}{100}$$
3. **Penalties & Bonuses Application**:
   $$\text{FinalScore} = \max\left(0, \min\left(100, \text{WeightedScore} - \text{PenaltyTotal} + \text{BonusTotal}\right)\right)$$

---

## 8. Score, Penalty & Bonus Formulas

### 8.1 Penalty Rules
* **Experience Deficit Penalty**: -5.0 points per year below minimum required experience.
* **Missing Mandatory Skill Penalty**: -10.0 points per missing mandatory skill (if not configured as hard knockout).
* **Penalty Cap**: Maximum total penalty = **-30.0 points**.

### 8.2 Bonus Rules
* **Extra Preferred Skill Bonus**: +2.0 points per matched preferred skill beyond core requirements.
* **Over-Qualification Bonus**: +5.0 points for advanced degree or 3+ additional experience years.
* **Bonus Cap**: Maximum total bonus = **+15.0 points**.

---

## 9. Confidence Formula

Confidence measures dataset completeness extracted during Stage 3:

$$\text{Confidence} = \frac{\text{Count of non-null extracted fields}}{\text{Total standard fields (12)}} \times 100$$

---

## 10. Recommendation Logic

Given `final_score` and `passing_score` (from Stage 5 weight config):

```text
               final_score < (passing_score - 15)  ──► NOT_RECOMMENDED
(passing_score - 15) <= final_score < passing_score  ──► NEEDS_REVIEW
 passing_score <= final_score < (passing_score + 15) ──► RECOMMENDED
               final_score >= (passing_score + 15)  ──► STRONG_MATCH
```

*Note*: Any candidate with `is_knocked_out == True` is immediately classified as `NOT_RECOMMENDED`.

---

## 11. API Contracts (`app/api/v1/endpoints/scoring.py`)

### 11.1 `POST /api/v1/projects/{project_id}/score`
* **Description**: Trigger scoring engines for all candidate resumes attached to a project.
* **Response (HTTP 200 OK)**: Returns `ProjectScoringResponse`.

### 11.2 `GET /api/v1/projects/{project_id}/scores`
* **Description**: Retrieve evaluated candidate scores for a project.
* **Response (HTTP 200 OK)**: Returns list of `CandidateScoreRead` DTOs.

### 11.3 `GET /api/v1/documents/{document_id}/score`
* **Description**: Retrieve detailed score breakdown for a specific candidate document.
* **Response (HTTP 200 OK)**: Returns single `CandidateScoreRead` DTO.

---

## 12. Error Handling & Custom Exceptions

Mapped to `app.core.exceptions.AppException`:

| Exception Class | HTTP Code | Error Code String | Trigger Scenario |
| :--- | :---: | :--- | :--- |
| `WeightConfigMissingException` | 400 | `WEIGHT_CONFIG_MISSING` | Project has no weight config configured in Stage 5 |
| `JobDescriptionMissingException` | 400 | `JOB_DESCRIPTION_MISSING` | Project has no job description attached |
| `ScoringFailedException` | 500 | `SCORING_EXECUTION_FAILED` | Internal error during Engine A or Engine B math |

---

## 13. Testing Strategy

### 13.1 Unit Tests (`tests/unit/`)
* `test_component_scoring_engine.py`: Test Engine A raw score calculations (0-100 boundary tests).
* `test_final_decision_engine.py`: Test Engine B weighted scores, penalty/bonus caps, confidence formula, and recommendation thresholds.

### 13.2 Integration Tests (`tests/integration/`)
* `test_scoring_repository.py`: Test PostgreSQL CRUD operations for `CandidateScoreModel`.

### 13.3 E2E Endpoint Tests (`tests/e2e/`)
* `test_scoring_api.py`: Test `POST /api/v1/projects/{project_id}/score`, `GET /scores`, and `GET /documents/{document_id}/score` via `httpx.AsyncClient`.

---

## 14. File Manifest for Codex Implementation

### Files to Create
```text
backend/app/models/scoring.py
backend/app/schemas/scoring.py
backend/app/repositories/scoring_repository.py
backend/app/services/scoring_service.py
backend/app/services/scoring/component_scoring_service.py
backend/app/services/scoring/final_decision_service.py
backend/app/api/v1/endpoints/scoring.py
backend/alembic/versions/<timestamp>_create_candidate_scores_table.py
tests/unit/test_component_scoring_engine.py
tests/unit/test_final_decision_engine.py
tests/integration/test_scoring_repository.py
tests/e2e/test_scoring_api.py
```

### Files to Modify
```text
backend/app/models/__init__.py        # Export CandidateScoreModel
backend/app/api/v1/router.py          # Mount scoring.py router
```
