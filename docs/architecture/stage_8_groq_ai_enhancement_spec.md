# Architecture Specification: Stage 8 Optional Groq AI Enhancement Layer

**Project**: `ai-resume-screener`  
**Subsystem**: Stage 8 – Optional Groq AI Enhancement Layer  
**Target Stack**: Python 3.12, FastAPI, SQLAlchemy 2.0 (Async), Groq API, HTTPX, Pydantic v2  
**Role**: Principal Software Architect  
**Status**: Approved Technical Specification for Codex Implementation  

---

## Executive Overview

This specification introduces an **Optional Groq AI Enhancement Layer** to Stage 8. It complements the existing deterministic Insight Engine by providing recruiter-friendly natural language rewrites of evaluation insights when enabled.

### Core Architectural Guarantees
1. **Zero Impact on Business Logic**: Groq is **NEVER** used for candidate scoring, ranking, penalties, bonuses, confidence metrics, or recommendation levels.
2. **Deterministic Single Source of Truth**: All numerical values, scores, percentages, skills, and decision classifications strictly originate from the Stage 1–7 deterministic pipeline.
3. **Anti-Hallucination Guardrails**: Groq functions exclusively as a natural language rewriter. It is strictly forbidden from inventing candidates, skills, experience years, degrees, or score values.
4. **Resilient Fallback**: If Groq is disabled (`ENABLE_AI_INSIGHTS=false`), unconfigured, rate-limited, or times out (>5s), the system seamlessly returns deterministic insights without raising HTTP 500 errors or blocking dashboard APIs.

---

## 1. System Architecture & Dual-Layer Pipeline

```mermaid
flowchart TD
    subgraph Deterministic Core Pipeline (Stages 1-7)
        S3[Stage 3: Extraction] --> S6[Stage 6: Component & Final Scoring]
        S6 --> S7[Stage 7: Deterministic Ranking]
    end

    S6 & S7 --> DetEngine[Deterministic Insight Engine]

    DetEngine --> CacheCheck{Cached Insight Exists?}
    CacheCheck -->|Yes| ReturnCache[Return Cached Insight]

    CacheCheck -->|No| FlagCheck{ENABLE_AI_INSIGHTS == True?}
    FlagCheck -->|False / Unconfigured| ReturnDet[Return Deterministic Insight & Cache]

    FlagCheck -->|True| GroqLayer[Groq AI Enhancement Layer]

    subgraph Groq Enhancement Pipeline
        GroqLayer --> PromptB[PromptBuilder: Inject Context & Anti-Hallucination Rules]
        PromptB --> GroqC[GroqClient: Async HTTPX Call to Groq API]
        GroqC -->|Success within 5s| ReturnAI[Return AI-Enhanced Insight & Cache]
        GroqC -->|Timeout / 429 / 503 Error| Fallback[FallbackHandler: Catch & Log Exception]
        Fallback --> ReturnDet
    end

    ReturnCache --> Client[FastAPI API Response]
    ReturnDet --> Client
    ReturnAI --> Client
```

---

## 2. Configuration & Environment Variables (`app/core/config.py`)

Add the following configuration settings to `Settings` in `app/core/config.py`:

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Groq AI Enhancement Layer Settings
    ENABLE_AI_INSIGHTS: bool = False
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_TIMEOUT_SECONDS: float = 5.0
    GROQ_MAX_RETRIES: int = 1
```

### Environment Variables Configuration (`.env` / `.env.example`)
```env
# Optional Groq AI Enhancement Settings
ENABLE_AI_INSIGHTS=false
GROQ_API_KEY=<YOUR_GROQ_API_KEY>
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_TIMEOUT_SECONDS=5.0
GROQ_MAX_RETRIES=1
```



---

## 3. Database Schema Update (`candidate_ai_insights` Table)

Extend the existing `candidate_ai_insights` table schema to support caching AI-enhanced insights:

```sql
-- Migration: Add AI enhancement metadata columns to candidate_ai_insights
ALTER TABLE candidate_ai_insights 
ADD COLUMN IF NOT EXISTS is_ai_enhanced BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS ai_model VARCHAR(64) NULL,
ADD COLUMN IF NOT EXISTS generation_latency_ms DOUBLE PRECISION NULL;
```

### SQLAlchemy Model Update (`app/models/insights.py`)
```text
app/models/insights.py
└── CandidateAIInsightModel
    ├── ... (existing fields)
    ├── is_ai_enhanced: Mapped[bool] (Boolean, default=False)
    ├── ai_model: Mapped[Optional[str]] (String(64), nullable=True)
    └── generation_latency_ms: Mapped[Optional[float]] (Float, nullable=True)
```

---

## 4. Subsystem Components Specification

### 4.1 Groq Client (`app/services/insights/groq_client.py`)
Encapsulates async HTTP communication with Groq API endpoint (`https://api.groq.com/openai/v1/chat/completions`):

* **Transport**: Uses `httpx.AsyncClient` with `timeout=settings.GROQ_TIMEOUT_SECONDS`.
* **Payload Format**: `response_format={"type": "json_object"}` to guarantee valid JSON returns matching schema.
* **Retry Protocol**: Catches HTTP 429 / 503 and retries `GROQ_MAX_RETRIES` times with exponential backoff (500ms).

### 4.2 Prompt Builder (`app/services/insights/prompt_builder.py`)
Constructs system and user prompts passing deterministic context:

* **System Prompt Guardrails**:
  ```text
  You are an expert HR Talent Acquisition Assistant. 
  Your ONLY task is to rewrite the provided deterministic candidate evaluation context into polished, professional recruiter narratives.
  
  STRICT RULES:
  1. Do NOT invent, estimate, or alter any scores, percentages, skills, experience years, degrees, or recommendations.
  2. Use ONLY the exact numbers, skills, and classification levels provided in the context.
  3. Output MUST be valid JSON matching the specified schema format.
  ```
* **User Context Payload**: Injects Candidate Name, Target Role, Final Score, Recommendation Level, Component Scores, Matched Skills, Missing Skills, Penalties, Bonuses, and Knockout Status.

### 4.3 Fallback Handler (`app/services/insights/fallback_handler.py`)
Catches any runtime failure during AI enhancement:

* **Intercepted Exceptions**: `httpx.TimeoutException`, `httpx.HTTPStatusError`, `json.JSONDecodeError`, `KeyError`, missing `GROQ_API_KEY`.
* **Action**:
  1. Emits structured log event `groq_api_fallback_triggered` with error detail and correlation ID.
  2. Immediately returns the original deterministic insight model with `is_ai_enhanced = False`.
  3. Guarantees zero request failure or HTTP 500 propagation to client.

### 4.4 AI Insight Facade Service (`app/services/insights/ai_insight_service.py`)
Coordinates insight generation lifecycle:

```python
async def get_candidate_insights(self, document_id: UUID4) -> CandidateInsightsRead:
    # 1. Check DB Cache
    cached = await self.repo.get_by_document_id(document_id)
    if cached:
        return CandidateInsightsRead.model_validate(cached)
    
    # 2. Generate Deterministic Baseline Insights
    det_insight = await self.deterministic_engine.generate(document_id)
    
    # 3. Check Feature Flag
    if not self.settings.ENABLE_AI_INSIGHTS or not self.settings.GROQ_API_KEY:
        await self.repo.save(det_insight)
        return det_insight

    # 4. Attempt Groq AI Enhancement
    try:
        ai_insight = await self.groq_enhancer.enhance(det_insight)
        await self.repo.save(ai_insight)
        return ai_insight
    except Exception as exc:
        return await self.fallback_handler.handle(exc, det_insight)
```

---

## 5. Pydantic Response Schema Update (`app/schemas/insights.py`)

Augment `CandidateInsightsRead` schema with AI enhancement metadata:

```python
class CandidateInsightsRead(BaseModel):
    document_id: UUID4
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    matched_skills: list[str]
    missing_skills: list[str]
    score_explanation: str
    recommendation_reason: str
    improvement_suggestions: list[str]
    
    # AI Enhancement Metadata
    is_ai_enhanced: bool = False
    ai_model: Optional[str] = None
    generation_latency_ms: Optional[float] = None
    model_config = ConfigDict(from_attributes=True)
```

---

## 6. Structured Logging Events

Log events track execution path, latency, and fallbacks:

```json
{
  "timestamp": "2026-08-06T18:20:00Z",
  "level": "INFO",
  "correlation_id": "c3094775-6804-4861-a0c3-04870f2095f9",
  "logger": "app.services.insights.ai_insight_service",
  "event": "groq_ai_enhancement_success",
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "model": "llama-3.3-70b-versatile",
  "is_ai_enhanced": true,
  "duration_ms": 1240.5
}
```

```json
{
  "timestamp": "2026-08-06T18:21:00Z",
  "level": "WARNING",
  "correlation_id": "8f0a23bc-11b3-461d-9e66-6b21bc089df2",
  "logger": "app.services.insights.fallback_handler",
  "event": "groq_api_fallback_triggered",
  "reason": "GROQ_API_TIMEOUT",
  "timeout_seconds": 5.0,
  "action": "Returned deterministic insights baseline successfully"
}
```

---

## 7. Testing Strategy

### 7.1 Unit Tests (`tests/unit/`)
* `test_prompt_builder.py`: Verify deterministic context injection and anti-hallucination prompt construction.
* `test_fallback_handler.py`: Mock Groq timeouts/HTTP 500 errors and verify zero exception propagation.
* `test_groq_client.py`: Mock Groq API JSON responses using `httpx.Response`.

### 7.2 Integration & E2E Tests (`tests/e2e/`)
* `test_ai_insights_api.py`:
  - Test `GET /api/v1/documents/{document_id}/insights` with `ENABLE_AI_INSIGHTS=false` -> Verifies `is_ai_enhanced == false`.
  - Test endpoint with `ENABLE_AI_INSIGHTS=true` and mocked Groq client -> Verifies `is_ai_enhanced == true`.

---

## 8. File Manifest for Codex Implementation

### Files to Create
```text
backend/app/services/insights/groq_client.py
backend/app/services/insights/prompt_builder.py
backend/app/services/insights/fallback_handler.py
backend/app/services/insights/ai_insight_service.py
backend/alembic/versions/<timestamp>_add_ai_enhancement_to_insights.py
tests/unit/test_prompt_builder.py
tests/unit/test_fallback_handler.py
tests/unit/test_groq_client.py
tests/e2e/test_ai_insights_api.py
```

### Files to Modify
```text
backend/app/core/config.py            # Add ENABLE_AI_INSIGHTS, GROQ_API_KEY, GROQ_MODEL
backend/.env.example                  # Add Groq configuration flags
backend/app/models/insights.py        # Add is_ai_enhanced, ai_model columns
backend/app/schemas/insights.py       # Add is_ai_enhanced, ai_model fields
backend/app/api/v1/endpoints/reporting.py # Inject AIInsightService into /insights endpoint
```
