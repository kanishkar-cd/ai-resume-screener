# Stage 4 Architecture Specification: Data Normalization

**Project**: `ai-resume-screener`  
**Subsystem**: Stage 4 - Deterministic Data Normalization  
**Target Stack**: Python 3.12, FastAPI, SQLAlchemy 2.0 Async, Alembic, PostgreSQL, Pydantic v2  
**Status**: Codex Implementation Specification  

## Purpose and boundaries

Stage 4 converts Stage 3 structured extraction output into stable canonical values suitable for a later scoring stage. It must be deterministic, idempotent, explainable, and versioned. Stage 3 records remain immutable inputs; normalization never overwrites extracted data.

Normalize only:

- Resume: skills, degree names, company names, job titles, dates, experience duration, phone, email casing, locations, languages, and certifications.
- Job description: skills, degree requirements, experience requirements, domain, and keywords.

Do not implement recruiter weights, scoring, ranking, matching, LLMs, embeddings, semantic search, or fuzzy semantic inference.

## 1. Database changes

Create one normalized record per source document.

### `normalized_resumes`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` |
| `document_id` | UUID | Unique, not null, FK `documents.id`, cascade delete |
| `extracted_resume_id` | UUID | Unique, not null, FK `extracted_resumes.id`, cascade delete |
| `skills` | JSONB | Not null, default `[]` |
| `education` | JSONB | Not null, default `[]` |
| `companies` | JSONB | Not null, default `[]` |
| `job_titles` | JSONB | Not null, default `[]` |
| `experience` | JSONB | Not null, default `[]` |
| `phone` | VARCHAR(32) | Nullable; E.164 when normalization is certain |
| `email` | VARCHAR(255) | Nullable; lowercase |
| `locations` | JSONB | Not null, default `[]` |
| `languages` | JSONB | Not null, default `[]` |
| `certifications` | JSONB | Not null, default `[]` |
| `normalization_metadata` | JSONB | Not null, default `{}` |
| `ruleset_version` | VARCHAR(32) | Not null |
| `created_at` | TIMESTAMPTZ | Not null, default now |
| `updated_at` | TIMESTAMPTZ | Not null, default now |

Indexes: `document_id`, `extracted_resume_id`, and GIN indexes on `skills` and `job_titles`.

### `normalized_job_descriptions`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` |
| `document_id` | UUID | Unique, not null, FK `documents.id`, cascade delete |
| `extracted_job_description_id` | UUID | Unique, not null, FK `extracted_job_descriptions.id`, cascade delete |
| `skills` | JSONB | Not null, default `[]` |
| `degree_requirements` | JSONB | Not null, default `[]` |
| `experience_requirements` | JSONB | Not null, default `[]` |
| `domain` | VARCHAR(255) | Nullable |
| `keywords` | JSONB | Not null, default `[]` |
| `normalization_metadata` | JSONB | Not null, default `{}` |
| `ruleset_version` | VARCHAR(32) | Not null |
| `created_at` | TIMESTAMPTZ | Not null, default now |
| `updated_at` | TIMESTAMPTZ | Not null, default now |

Indexes: `document_id`, `extracted_job_description_id`, and a GIN index on `skills`.

Add `NORMALIZATION` to `processing_stage_enum`. Runtime transitions are `COMPLETED` (Stage 3 output available) -> `NORMALIZATION` -> `COMPLETED`, or `FAILED`. Do not alter existing Stage 1-3 API behavior.

`normalization_metadata` must contain:

```json
{
  "ruleset_version": "1.0.0",
  "normalized_at": "2026-08-06T16:00:00Z",
  "changes": [
    {"field": "skills", "source": "Py", "canonical": "Python", "rule": "skill_alias"}
  ],
  "warnings": [],
  "field_confidence": {"skills": 1.0, "phone": 0.95}
}
```

Do not create scoring, weighting, or matching tables.

## 2. SQLAlchemy models

Create `app/models/normalized_info.py`:

- `NormalizedResumeModel(Base, UUIDMixin, TimestampMixin)`
- `NormalizedJobDescriptionModel(Base, UUIDMixin, TimestampMixin)`

Use PostgreSQL JSONB, typed SQLAlchemy 2.0 `Mapped` fields, named indexes, database foreign keys, and one-to-one relationships.

Relationships:

- `DocumentModel.normalized_resume` <-> `NormalizedResumeModel.document`
- `DocumentModel.normalized_job_description` <-> `NormalizedJobDescriptionModel.document`
- `ExtractedResumeModel.normalized_resume` <-> `NormalizedResumeModel.extracted_resume`
- `ExtractedJobDescriptionModel.normalized_job_description` <-> `NormalizedJobDescriptionModel.extracted_job_description`

The normalized models own no business behavior. Mutable JSON defaults must use callables, never shared list/dict instances.

## 3. Pydantic schemas

Create `app/schemas/normalized_info.py` with strict DTOs:

```text
CanonicalEducationItem
- degree: str | None
- field_of_study: str | None
- institution: str | None
- graduation_date: str | None       # ISO partial/full date

CanonicalExperienceItem
- company: str | None
- job_title: str | None
- start_date: str | None            # YYYY, YYYY-MM, or YYYY-MM-DD
- end_date: str | None
- is_current: bool
- duration_months: int | None
- duration_display: str | None      # e.g. "3 years 2 months"

CanonicalLocation
- city: str | None
- region: str | None
- country: str | None
- country_code: str | None          # ISO 3166-1 alpha-2
- display_name: str

CanonicalExperienceRequirement
- minimum_months: int | None
- maximum_months: int | None
- display_value: str

NormalizationChange
- field: str
- source: str | None
- canonical: str | None
- rule: str

NormalizationMetadata
- ruleset_version: str
- normalized_at: datetime
- changes: list[NormalizationChange]
- warnings: list[str]
- field_confidence: dict[str, float] # every value in [0, 1]
```

Also implement:

- `NormalizedResumeCreate`, `NormalizedResumeRead`
- `NormalizedJobDescriptionCreate`, `NormalizedJobDescriptionRead`
- `NormalizeDocumentResponse`
- `NormalizeResponseEnvelope`
- `NormalizedDocumentResponse` as the resume/JD response union

All list and dictionary fields use `default_factory`. Read DTOs use `ConfigDict(from_attributes=True)`. OpenAPI examples must show both document types and normalization changes.

## 4. Repository responsibilities

Create `app/repositories/normalization_repository.py`.

`NormalizationRepository` exposes only persistence operations:

```python
create_or_update_resume(data) -> NormalizedResumeModel
create_or_update_job_description(data) -> NormalizedJobDescriptionModel
get_resume_by_document_id(document_id) -> NormalizedResumeModel | None
get_job_description_by_document_id(document_id) -> NormalizedJobDescriptionModel | None
delete_resume_by_document_id(document_id) -> bool
delete_job_description_by_document_id(document_id) -> bool
```

Upserts must preserve the normalized record ID, replace all derived fields atomically, update the ruleset version, and commit once. Repository methods contain no standardization rules or exception-to-HTTP translation.

## 5. Service responsibilities

Create `app/services/normalization_service.py`.

`NormalizationService` must:

1. Retrieve the active document.
2. Select the correct Stage 3 extracted record by `document_type`.
3. Reject missing extracted data.
4. Set the document to `NORMALIZATION/IN_PROGRESS` and clear stale errors.
5. Invoke the matching deterministic normalizer.
6. Upsert the normalized record.
7. Set the document to `COMPLETED/COMPLETED`.
8. On pipeline or persistence failure, set `FAILED/FAILED`, store a bounded `error_message`, and translate the exception.
9. Return existing data without duplication; rerunning with the same ruleset and same extracted input must produce the same canonical values.

Expose business methods:

```python
normalize_document_data(document_id: UUID) -> NormalizeDocumentResponse
get_normalized_data(document_id: UUID) -> NormalizedResumeRead | NormalizedJobDescriptionRead
```

Keep normalization transport-independent so it can later run in a task worker without changing business logic. Do not invoke Stage 2 parsing or Stage 3 extraction automatically.

## 6. Normalization pipeline

Create:

```text
app/services/normalizers/
  resume_normalizer.py
  job_description_normalizer.py
app/services/pipeline/normalization_rules.py
app/services/pipeline/canonical_dictionaries.py
```

Processing order:

```text
Stage 3 structured record
  -> trim and Unicode/case comparison preparation
  -> exact alias lookup
  -> deterministic pattern conversion
  -> canonical structured mapping
  -> stable deduplication
  -> validation
  -> audit changes, warnings, and confidence
  -> normalized record
```

Canonical dictionaries are version-controlled Python/JSON assets with a single `RULESET_VERSION`. Alias keys use Unicode NFKC, trimmed whitespace, collapsed internal spaces, punctuation-aware comparison, and case folding. Canonical output retains prescribed display casing.

No fuzzy, vector, semantic, probabilistic, or LLM-based matching is permitted. Unknown values are preserved after safe whitespace cleanup and recorded as warnings; they must never be silently discarded or guessed.

## 7. Standardization rules

### Shared rules

- Trim values, apply Unicode NFKC, collapse repeated whitespace, remove empty items.
- Match aliases case-insensitively; emit canonical display values.
- Deduplicate by canonical case-folded value while preserving first-seen order.
- Do not change Stage 3 confidence. Record a separate normalization confidence: exact canonical value `1.0`, known alias `0.95`, deterministic regex conversion `0.90`, preserved unknown `0.50`.
- Every changed or unresolved value must appear in metadata.

### Resume

- **Skills**: exact alias map. Examples: `Py` -> `Python`, `postgres` -> `PostgreSQL`, `nodejs` -> `Node.js`. `C++ Developer` is a job title, not a skill alias.
- **Degrees**: canonical degree taxonomy. `B.E.`, `BE`, and `Bachelor of Engg` -> `Bachelor of Engineering`; preserve field of study separately.
- **Companies**: normalize legal suffix punctuation (`Corp.` -> `Corporation`, `Pvt. Ltd.` -> `Private Limited`) and apply a curated exact alias map. Never infer that similarly named companies are identical.
- **Job titles**: exact title taxonomy. `C++ Developer` -> `Software Engineer`; `Sr. Backend Dev` -> `Senior Backend Engineer`. Apply to the resume designation and every experience title.
- **Dates**: output ISO `YYYY`, `YYYY-MM`, or `YYYY-MM-DD` based only on available precision. Map `Present`, `Current`, and `Now` to `end_date=null`, `is_current=true`. Reject impossible dates.
- **Experience duration**: calculate inclusive calendar-month difference when valid start/end dates exist; otherwise parse deterministic expressions. `3 yrs` -> `36` months and display `3 years`. Do not double-count overlapping roles when calculating any aggregate duration; Stage 4 need not create an aggregate unless explicitly added later.
- **Phone**: remove formatting and output E.164 only when an explicit country code is present. `+91-98765-43210` -> `+919876543210`. Do not guess a country code from an unqualified local number; preserve it and emit a warning.
- **Email**: trim and lowercase the complete address. Do not alter characters within the local part beyond casing.
- **Locations**: map exact known aliases to structured city/region/country/ISO country code. Preserve unknown display text; do not geocode.
- **Languages**: use canonical English language names and ISO 639-1 codes if the schema is later extended. Example: `Eng` -> `English`.
- **Certifications**: canonical vendor and certification names through exact aliases; preserve certification level/version when present.

### Job description

- **Skills**: use the same skill taxonomy as resumes.
- **Degree requirements**: use the same degree taxonomy; retain multiple alternatives and requirement wording in metadata.
- **Experience requirements**: convert `3 yrs`, `3+ years`, and `3-5 years` into minimum/maximum months plus a canonical display value. `3+ years` has `minimum_months=36`, `maximum_months=null`.
- **Domain**: exact alias taxonomy, such as `IT`, `Software Development`, and `Software Engineering` -> `Software Engineering`. Unknown domains are preserved.
- **Keywords**: NFKC/trim/case-fold for comparison, map aliases shared with skills/titles/domains, emit canonical display casing, and stably deduplicate. Do not generate new keywords.

## 8. API contracts

Mount under the existing `/api/v1/documents` router.

### `POST /api/v1/documents/{document_id}/normalize`

Triggers deterministic normalization of the corresponding Stage 3 record.

- Success: `200 OK`
- Request body: none
- Idempotent: repeated calls upsert the same record

```json
{
  "data": {
    "document_id": "550e8400-e29b-41d4-a716-446655440000",
    "document_type": "RESUME",
    "processing_stage": "COMPLETED",
    "ruleset_version": "1.0.0",
    "message": "Document data normalized successfully."
  }
}
```

### `GET /api/v1/documents/{document_id}/normalized`

Returns the normalized resume or job-description DTO, including `normalization_metadata`, `ruleset_version`, and timestamps.

- Success: `200 OK`
- Missing active document or normalized output: `404 Not Found`

Both operations must define response models, status codes, summaries, descriptions, UUID examples, resume/JD examples, and error response models in Swagger.

Do not add list, scoring, comparison, match, or ranking endpoints.

## 9. Error handling

All public exceptions extend `AppException` and use the existing error envelope.

| Exception | HTTP | Code | Condition |
|---|---:|---|---|
| `DocumentNotFoundException` | 404 | `DOCUMENT_NOT_FOUND` | Missing or soft-deleted document |
| `ExtractedDataNotFoundException` | 400 | `EXTRACTED_DATA_NOT_FOUND` | Stage 3 output is unavailable |
| `NormalizedDataNotFoundException` | 404 | `NORMALIZED_DATA_NOT_FOUND` | GET before normalization |
| `UnsupportedNormalizationTypeException` | 422 | `UNSUPPORTED_NORMALIZATION_TYPE` | Unsupported document type |
| `NormalizationValidationException` | 422 | `NORMALIZATION_VALIDATION_FAILED` | Canonical result violates schema/rules |
| `NormalizationFailedException` | 500 | `NORMALIZATION_FAILED` | Unexpected pipeline or persistence failure |

Unknown aliases are not request failures. Preserve them and add a warning. Failed normalization must not partially replace the last valid normalized record.

## 10. Testing strategy

### Unit tests

- Every alias dictionary and canonical output casing.
- Skill and keyword boundary matching.
- Degree, company, title, domain, language, and certification mappings.
- ISO date conversion, partial dates, current roles, invalid dates, and month calculations.
- Experience ranges and open-ended minimums.
- E.164 conversion and ambiguous local-number warnings.
- Email lowercasing and location mapping.
- Stable deduplication, unknown preservation, audit changes, confidence, and idempotency.
- Resume and job-description normalizers using complete representative fixtures.

### Repository integration tests

- Resume and JD create, fetch, and update-in-place.
- Unique document constraints and foreign-key cascade.
- JSONB persistence and ruleset-version updates.
- Transaction rollback retains the previous valid normalized record.

### Service tests

- Correct normalizer selection by document type.
- Required Stage 3 input.
- `NORMALIZATION -> COMPLETED` transition.
- `FAILED` transition and bounded error message.
- Duplicate normalization remains one database row.
- Unknown values succeed with warnings.

### API tests

- POST and GET for resume and job description.
- Swagger/OpenAPI response schemas and examples.
- Missing, deleted, unextracted, unnormalized, invalid UUID, validation failure, and internal pipeline failure.
- Confirm all Stage 1-3 endpoint tests remain unchanged and passing.

## Completion criteria

Stage 4 is complete only when a future implementation satisfies all of the following:

- Alembic is at the new head.
- Resume and job-description normalization persist independently from Stage 3.
- Both normalization endpoints appear in Swagger.
- Canonical mappings and audit metadata are deterministic and versioned.
- Reprocessing is idempotent.
- Processing stages and failures are persisted correctly.
- All Stage 1-4 tests pass.
- No excluded Stage 5 or AI functionality is present.

## Implementation file manifest

```text
backend/app/models/normalized_info.py
backend/app/schemas/normalized_info.py
backend/app/repositories/normalization_repository.py
backend/app/services/normalization_service.py
backend/app/services/normalizers/resume_normalizer.py
backend/app/services/normalizers/job_description_normalizer.py
backend/app/services/pipeline/normalization_rules.py
backend/app/services/pipeline/canonical_dictionaries.py
backend/app/api/v1/endpoints/normalization.py
backend/alembic/versions/<revision>_create_normalized_tables.py
backend/tests/unit/test_normalization_rules.py
backend/tests/unit/test_resume_normalizer.py
backend/tests/unit/test_job_description_normalizer.py
backend/tests/integration/test_normalization_repository.py
backend/tests/e2e/test_normalization_api.py
```

Permitted existing-file changes are limited to model exports and relationships, the API v1 router, the processing-stage enum/schema, and Alembic metadata imports.
