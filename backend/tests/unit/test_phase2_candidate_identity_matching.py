"""Unit tests for Phase 2: Deterministic Candidate Identity Matching Engine.

Covers:
1. Rule 1: Zoho Candidate ID matching, name conflict checks, unmapped fallbacks,
   attachment ID isolation, multiple resumes for same candidate.
2. Rule 2: Normalized email matching, single consistent match, conflicting names,
   conflicting Zoho IDs, multiple records with conflicting names, invalid/dummy email handling.
3. Rule 3: Normalized phone matching, supporting name confirmation, conflicting names,
   shared phone numbers, ambiguous phone match without name.
4. Rule 4: Candidate name matching rules, non-merging on name alone, `are_names_conflicting` logic.
5. Rule 5: New candidate determination vs missing contact information review requirement.
6. Edge cases: Exclude current document ID, schema integrity, dict & model inputs.
"""

from uuid import uuid4
import pytest

from app.schemas.candidate_identity import (
    CandidateIdentityInput,
    CandidateIdentityMatchResult,
    CandidateIdentityRecord,
    CandidateIdentityStatus,
    IdentityMatchMethod,
)
from app.services.candidate_identity_service import (
    CandidateIdentityService,
    are_names_conflicting,
)


# ==============================================================================
# Helper Fixtures & Data
# ==============================================================================

@pytest.fixture
def identity_service() -> CandidateIdentityService:
    """Service instance without database session (uses existing_records for in-memory testing)."""
    return CandidateIdentityService(session=None)


# ==============================================================================
# 1. Rule 1: Zoho Candidate ID Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_zoho_candidate_id_mapped_match(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Alice Smith",
            email="alice.smith@example.com",
            phone="+16502345678",
            zoho_candidate_id="ZC-10001",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Alice Smith",
        email="alice.smith@example.com",
        phone="+16502345678",
        zoho_candidate_id="ZC-10001",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.EXISTING_CANDIDATE
    assert result.matched_candidate_id == doc_id
    assert result.match_method == IdentityMatchMethod.ZOHO_CANDIDATE_ID
    assert result.confidence == 1.0
    assert not result.conflicts


@pytest.mark.asyncio
async def test_zoho_candidate_id_with_compatible_name(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Arun Kumar",
            email="arun.kumar@example.com",
            zoho_candidate_id="ZC-10002",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Arun Kumar K.",
        email="arun.kumar@example.com",
        zoho_candidate_id="ZC-10002",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.EXISTING_CANDIDATE
    assert result.matched_candidate_id == doc_id
    assert result.match_method == IdentityMatchMethod.ZOHO_CANDIDATE_ID
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_zoho_candidate_id_name_conflict_triggers_review(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Alice Smith",
            email="alice@example.com",
            zoho_candidate_id="ZC-10003",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Bob Jones",
        email="bob@example.com",
        zoho_candidate_id="ZC-10003",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.REVIEW_REQUIRED
    assert result.match_method == IdentityMatchMethod.ZOHO_CANDIDATE_ID
    assert len(result.conflicts) > 0
    assert result.conflicts[0]["type"] == "NAME_CONFLICT_ON_ZOHO_ID"


@pytest.mark.asyncio
async def test_zoho_candidate_id_unmapped_falls_back_to_email(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Charlie Brown",
            email="charlie@example.com",
            zoho_candidate_id=None,  # Not linked to Zoho yet
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Charlie Brown",
        email="charlie@example.com",
        zoho_candidate_id="ZC-UNMAPPED-999",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    # Zoho ID didn't match, but email matched existing candidate!
    assert result.status == CandidateIdentityStatus.EXISTING_CANDIDATE
    assert result.matched_candidate_id == doc_id
    assert result.match_method == IdentityMatchMethod.NORMALIZED_EMAIL


@pytest.mark.asyncio
async def test_zoho_attachment_id_never_treated_as_candidate_id(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Diana Prince",
            email="diana@example.com",
            zoho_attachment_id="ATTACH-555",
            zoho_candidate_id="ZC-REAL-CANDIDATE",
        )
    ]
    # Input accidentally sets zoho_candidate_id equal to attachment ID
    inp = CandidateIdentityInput(
        candidate_name="Different Person",
        email="different@example.com",
        zoho_candidate_id="ATTACH-555",
        zoho_attachment_id="ATTACH-555",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    # ATTACH-555 is rejected as a candidate ID; no candidate matches -> NEW_CANDIDATE
    assert result.status == CandidateIdentityStatus.NEW_CANDIDATE
    assert result.matched_candidate_id is None


@pytest.mark.asyncio
async def test_multiple_resumes_same_zoho_candidate(identity_service: CandidateIdentityService) -> None:
    doc1 = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc1,
            candidate_name="Eva Green",
            email="eva@example.com",
            zoho_candidate_id="ZC-EVA-1",
            zoho_attachment_id="RESUME-V1",
        )
    ]
    # Ingesting second resume for same Zoho candidate with new attachment ID
    inp = CandidateIdentityInput(
        candidate_name="Eva Green",
        email="eva@example.com",
        zoho_candidate_id="ZC-EVA-1",
        zoho_attachment_id="RESUME-V2",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.EXISTING_CANDIDATE
    assert result.matched_candidate_id == doc1


# ==============================================================================
# 2. Rule 2: Normalized Email Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_email_single_consistent_match(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Frank Miller",
            email="  Frank.Miller@Example.COM  ",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Frank Miller",
        email="frank.miller@example.com",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.EXISTING_CANDIDATE
    assert result.matched_candidate_id == doc_id
    assert result.match_method == IdentityMatchMethod.NORMALIZED_EMAIL
    assert result.confidence == 0.95


@pytest.mark.asyncio
async def test_email_match_with_name_conflict_triggers_review(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="George Clark",
            email="shared.email@example.com",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Hannah Davis",
        email="shared.email@example.com",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.REVIEW_REQUIRED
    assert result.matched_candidate_id == doc_id
    assert result.match_method == IdentityMatchMethod.NORMALIZED_EMAIL
    assert any(c["type"] == "NAME_CONFLICT_ON_EMAIL" for c in result.conflicts)


@pytest.mark.asyncio
async def test_email_match_with_conflicting_zoho_id_triggers_review(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Ian Malcolm",
            email="ian.malcolm@example.com",
            zoho_candidate_id="ZC-ORIGINAL-ID",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Ian Malcolm",
        email="ian.malcolm@example.com",
        zoho_candidate_id="ZC-DIFFERENT-ID",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.REVIEW_REQUIRED
    assert any(c["type"] == "ZOHO_ID_CONFLICT_ON_EMAIL" for c in result.conflicts)


@pytest.mark.asyncio
async def test_email_multiple_records_with_conflicting_names_triggers_review(identity_service: CandidateIdentityService) -> None:
    doc1 = str(uuid4())
    doc2 = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc1,
            candidate_name="Jack Ryan",
            email="duplicate@agency.com",
        ),
        CandidateIdentityRecord(
            document_id=doc2,
            candidate_name="Jill Valentine",
            email="duplicate@agency.com",
        ),
    ]
    inp = CandidateIdentityInput(
        candidate_name="Jack Ryan",
        email="duplicate@agency.com",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.REVIEW_REQUIRED
    assert any(c["type"] == "MULTIPLE_CONFLICTING_NAMES_ON_EMAIL" for c in result.conflicts)


@pytest.mark.asyncio
async def test_email_invalid_not_used_for_matching(identity_service: CandidateIdentityService) -> None:
    existing = [
        CandidateIdentityRecord(
            document_id=str(uuid4()),
            candidate_name="Karen Page",
            email=None,
            phone="+16502345678",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Karen Page",
        email="not-an-email",
        phone="+16502345678",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    # Invalid email ignored, falls through to valid phone match
    assert result.status == CandidateIdentityStatus.EXISTING_CANDIDATE
    assert result.match_method == IdentityMatchMethod.NORMALIZED_PHONE


# ==============================================================================
# 3. Rule 3: Normalized Phone Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_phone_match_with_supporting_name(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Leo Fitz",
            phone="+91 98765 43210",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Leo Fitz",
        phone="09876543210",  # Resolves to +919876543210
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.EXISTING_CANDIDATE
    assert result.matched_candidate_id == doc_id
    assert result.match_method == IdentityMatchMethod.NORMALIZED_PHONE
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_phone_match_with_conflicting_name_triggers_review(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Maya Lin",
            phone="+91 98765 43210",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Noah Bennett",
        phone="+91 98765 43210",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.REVIEW_REQUIRED
    assert result.match_method == IdentityMatchMethod.NORMALIZED_PHONE
    assert any(c["type"] == "NAME_CONFLICT_ON_PHONE" for c in result.conflicts)


@pytest.mark.asyncio
async def test_shared_phone_across_multiple_distinct_candidates(identity_service: CandidateIdentityService) -> None:
    doc1 = str(uuid4())
    doc2 = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc1,
            candidate_name="Oliver Queen",
            email="oliver@star.org",
            phone="+16502345678",
        ),
        CandidateIdentityRecord(
            document_id=doc2,
            candidate_name="Felicity Smoak",
            email="felicity@star.org",
            phone="+16502345678",
        ),
    ]
    inp = CandidateIdentityInput(
        candidate_name="Oliver Queen",
        phone="+16502345678",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.REVIEW_REQUIRED
    assert any(c["type"] == "SHARED_PHONE_NUMBER" for c in result.conflicts)


@pytest.mark.asyncio
async def test_phone_match_without_name_support_triggers_review(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name=None,  # Existing record has no name
            phone="+91 98765 43210",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Peter Parker",
        phone="+91 98765 43210",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    # Phone matches, but name confirmation is insufficient -> ambiguous
    assert result.status == CandidateIdentityStatus.REVIEW_REQUIRED
    assert any(c["type"] == "AMBIGUOUS_PHONE_MATCH_WITHOUT_NAME" for c in result.conflicts)


# ==============================================================================
# 4. Rule 4: Candidate Name & Conflict Detection Tests
# ==============================================================================

def test_are_names_conflicting_identical_and_case() -> None:
    assert not are_names_conflicting("John Doe", "john doe")
    assert not are_names_conflicting("Harshini CS", "Harshini CS")


def test_are_names_conflicting_subsets_and_initials() -> None:
    assert not are_names_conflicting("Arun Kumar", "Arun Kumar K.")
    assert not are_names_conflicting("John Kennedy", "John F. Kennedy")
    assert not are_names_conflicting("Harshini", "Harshini CS")
    assert not are_names_conflicting("Robert Downey", "Robert Downey Jr.")


def test_are_names_conflicting_positive_conflicts() -> None:
    assert are_names_conflicting("Alice Smith", "Bob Smith")
    assert are_names_conflicting("Rahul Sharma", "Priya Patel")
    assert are_names_conflicting("John Doe", "Jane Doe")


def test_are_names_conflicting_missing_or_invalid() -> None:
    assert not are_names_conflicting(None, "Alice Smith")
    assert not are_names_conflicting("Alice Smith", "")
    assert not are_names_conflicting("N/A", "Alice Smith")
    assert not are_names_conflicting("Resume", "Candidate")


@pytest.mark.asyncio
async def test_name_alone_never_merges_candidate(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Quinn Fabray",
            email="quinn1@school.edu",
            phone="+16501112222",
        )
    ]
    # Same name, completely different contact info
    inp = CandidateIdentityInput(
        candidate_name="Quinn Fabray",
        email="quinn2@different.edu",
        phone="+16503334444",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    # Must NOT automatically merge on name alone! Must be classified as NEW_CANDIDATE
    assert result.status == CandidateIdentityStatus.NEW_CANDIDATE
    assert result.matched_candidate_id is None


# ==============================================================================
# 5. Rule 5: New Candidate vs Insufficient Information Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_clean_new_candidate(identity_service: CandidateIdentityService) -> None:
    existing = [
        CandidateIdentityRecord(
            document_id=str(uuid4()),
            candidate_name="Existing Person",
            email="existing@example.com",
        )
    ]
    inp = CandidateIdentityInput(
        candidate_name="Brand New Person",
        email="brand.new@example.com",
        phone="+91 9988776655",
    )
    result = await identity_service.match_identity(inp, existing_records=existing)

    assert result.status == CandidateIdentityStatus.NEW_CANDIDATE
    assert result.confidence == 1.0
    assert result.matched_candidate_id is None
    assert not result.conflicts


@pytest.mark.asyncio
async def test_missing_contact_info_triggers_review_not_new_candidate(identity_service: CandidateIdentityService) -> None:
    inp = CandidateIdentityInput(
        candidate_name="Nameless Without Contact",
        email="",
        phone=None,
    )
    result = await identity_service.match_identity(inp, existing_records=[])

    # Rule 5: Missing contact information alone must NOT be treated as proof of new candidate
    assert result.status == CandidateIdentityStatus.REVIEW_REQUIRED
    assert result.confidence == 0.0
    assert result.matched_candidate_id is None
    assert any(c["type"] == "INSUFFICIENT_IDENTITY_DATA" for c in result.conflicts)


@pytest.mark.asyncio
async def test_valid_email_only_is_sufficient_for_new_candidate(identity_service: CandidateIdentityService) -> None:
    inp = CandidateIdentityInput(
        candidate_name="Email Only Person",
        email="valid.email.only@example.com",
        phone=None,
    )
    result = await identity_service.match_identity(inp, existing_records=[])

    assert result.status == CandidateIdentityStatus.NEW_CANDIDATE
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_valid_phone_only_is_sufficient_for_new_candidate(identity_service: CandidateIdentityService) -> None:
    inp = CandidateIdentityInput(
        candidate_name="Phone Only Person",
        email="",
        phone="+91 9876543210",
    )
    result = await identity_service.match_identity(inp, existing_records=[])

    assert result.status == CandidateIdentityStatus.NEW_CANDIDATE
    assert result.confidence == 1.0


# ==============================================================================
# 6. Edge Cases & Integration Helpers
# ==============================================================================

@pytest.mark.asyncio
async def test_exclude_current_document_id(identity_service: CandidateIdentityService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Self Matching",
            email="self@example.com",
        )
    ]
    inp = CandidateIdentityInput(
        document_id=doc_id,
        candidate_name="Self Matching",
        email="self@example.com",
    )
    # When excluding current document ID (e.g. during re-processing), it should not match itself
    result = await identity_service.match_identity(
        inp,
        existing_records=existing,
        exclude_document_id=doc_id,
    )
    assert result.status == CandidateIdentityStatus.NEW_CANDIDATE
    assert result.matched_candidate_id is None


@pytest.mark.asyncio
async def test_dict_input_support(identity_service: CandidateIdentityService) -> None:
    raw_dict = {
        "candidate_name": "Dict Candidate",
        "email": "dict@example.com",
        "phone": "+1 650 234 5678",
    }
    result = await identity_service.match_identity(raw_dict, existing_records=[])
    assert result.status == CandidateIdentityStatus.NEW_CANDIDATE
    assert result.normalized_identity["candidate_name"] == "Dict Candidate"
    assert result.normalized_identity["email"] == "dict@example.com"
