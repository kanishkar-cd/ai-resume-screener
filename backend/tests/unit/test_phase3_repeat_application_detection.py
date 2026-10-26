"""Unit tests for Phase 3: Deterministic Repeat Application Detection Engine.

Covers:
1. Rule 1: Candidate identity resolution (via Phase 2 matching engine),
   handling new candidates, ambiguous identity review required, and preserving Zoho Candidate IDs.
2. Rule 2: Current job opening identification (Zoho imports, manual uploads, missing opening handling).
3. Rule 3: Application history search and deterministic classification:
   - FIRST_APPLICATION
   - REPEAT_APPLICATION_SAME_JOB
   - REPEAT_APPLICATION_DIFFERENT_JOB
   - MULTIPLE_PREVIOUS_APPLICATIONS
   - IDENTITY_REVIEW_REQUIRED
   - JOB_OPENING_REQUIRED
4. Rule 4: False positive prevention:
   - Multiple resume attachments grouped into one application.
   - Reprocessing same document does not trigger repeat application.
   - Re-uploading resume to existing application does not falsely trigger repeat status.
5. End-to-end integration and input flexibility (dict vs Pydantic).
"""

from uuid import uuid4
import pytest

from app.schemas.candidate_identity import (
    CandidateIdentityInput,
    CandidateIdentityRecord,
)
from app.schemas.repeat_application import (
    ApplicationHistoryItem,
    RepeatApplicationInput,
    RepeatApplicationResult,
    RepeatApplicationStatus,
)
from app.services.candidate_identity_service import CandidateIdentityService
from app.services.repeat_application_service import RepeatApplicationService


# ==============================================================================
# Helper Fixtures & Setup
# ==============================================================================

@pytest.fixture
def identity_service() -> CandidateIdentityService:
    return CandidateIdentityService(session=None)


@pytest.fixture
def repeat_service(identity_service: CandidateIdentityService) -> RepeatApplicationService:
    return RepeatApplicationService(session=None, identity_service=identity_service)


# ==============================================================================
# 1. Rule 1: Candidate Identity Resolution Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_new_candidate_returns_first_application(repeat_service: RepeatApplicationService) -> None:
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="New Candidate",
            email="brand.new.applicant@example.com",
            phone="+16502345678",
        ),
        job_opening_id="ZO-100",
        job_title="Software Engineer",
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=[])

    assert result.status == RepeatApplicationStatus.FIRST_APPLICATION
    assert result.is_repeat is False
    assert result.total_previous_applications == 0
    assert not result.previous_applications


@pytest.mark.asyncio
async def test_identity_review_required_returns_identity_review_required(
    repeat_service: RepeatApplicationService,
) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Alice Smith",
            email="conflicted@example.com",
        )
    ]
    # Input has same email but completely conflicting candidate name
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Bob Jones",
            email="conflicted@example.com",
        ),
        job_opening_id="ZO-100",
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    assert result.status == RepeatApplicationStatus.IDENTITY_REVIEW_REQUIRED
    assert result.is_repeat is False
    assert result.identity_match_result is not None
    assert result.identity_match_result.status.value == "REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_zoho_candidate_id_preserved_in_result(repeat_service: RepeatApplicationService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Claire Underwood",
            email="claire@whitehouse.gov",
            zoho_candidate_id="ZC-CLAIRE-1",
            job_opening_id="ZO-GOV-1",
        )
    ]
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Claire Underwood",
            email="claire@whitehouse.gov",
            zoho_candidate_id="ZC-CLAIRE-1",
        ),
        job_opening_id="ZO-GOV-2",
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    assert result.zoho_candidate_id == "ZC-CLAIRE-1"
    assert result.candidate_id == doc_id
    assert result.status == RepeatApplicationStatus.REPEAT_APPLICATION_DIFFERENT_JOB
    assert result.is_repeat is True


@pytest.mark.asyncio
async def test_attachment_id_never_used_as_candidate_id(repeat_service: RepeatApplicationService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Real Person",
            email="real@example.com",
            zoho_candidate_id="ZC-REAL",
            zoho_attachment_id="ATT-12345",
        )
    ]
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Unrelated Person",
            email="unrelated@example.com",
            zoho_candidate_id="ATT-12345",  # Attachment ID falsely supplied as candidate ID
            zoho_attachment_id="ATT-12345",
        ),
        job_opening_id="ZO-100",
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    # Attachment ID is rejected as candidate ID; unrelated person is treated as new candidate
    assert result.status == RepeatApplicationStatus.FIRST_APPLICATION
    assert result.is_repeat is False


# ==============================================================================
# 2. Rule 2: Current Job Opening Identification Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_missing_job_opening_and_project_returns_job_opening_required(
    repeat_service: RepeatApplicationService,
) -> None:
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Manual Upload Without Job",
            email="manual@example.com",
        ),
        job_opening_id=None,
        project_id=None,
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=[])

    assert result.status == RepeatApplicationStatus.JOB_OPENING_REQUIRED
    assert result.is_repeat is False
    assert any("current job opening cannot be determined" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_manual_upload_with_project_id_identifies_job(
    repeat_service: RepeatApplicationService,
) -> None:
    proj_id = uuid4()
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Manual Ingest",
            email="manual.ingest@example.com",
            phone="+919876543210",
        ),
        project_id=proj_id,
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=[])

    assert result.current_project_id == str(proj_id)
    assert result.status == RepeatApplicationStatus.FIRST_APPLICATION


# ==============================================================================
# 3. Rule 3: Search Application History & Classification Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_first_application_when_no_prior_history(repeat_service: RepeatApplicationService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Danielle Rousseau",
            email="danielle@island.org",
            job_opening_id=None,
            project_id=None,
        )
    ]
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Danielle Rousseau",
            email="danielle@island.org",
        ),
        job_opening_id="JOB-SURVIVOR",
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    assert result.status == RepeatApplicationStatus.FIRST_APPLICATION
    assert result.is_repeat is False
    assert result.total_previous_applications == 0


@pytest.mark.asyncio
async def test_repeat_application_different_job(repeat_service: RepeatApplicationService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Ethan Hunt",
            email="ethan.hunt@imf.gov",
            job_opening_id="JOB-MISSION-1",
            job_title="Field Operative",
        )
    ]
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Ethan Hunt",
            email="ethan.hunt@imf.gov",
        ),
        job_opening_id="JOB-MISSION-2",
        job_title="Team Lead",
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    assert result.status == RepeatApplicationStatus.REPEAT_APPLICATION_DIFFERENT_JOB
    assert result.is_repeat is True
    assert result.total_previous_applications == 1
    assert result.previous_applications[0].job_opening_id == "JOB-MISSION-1"
    assert result.previous_applications[0].is_same_job is False


@pytest.mark.asyncio
async def test_repeat_application_same_job(repeat_service: RepeatApplicationService) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Fiona Gallagher",
            email="fiona@southside.com",
            job_opening_id="JOB-RETAIL-101",
            job_title="Store Manager",
        )
    ]
    # Re-applying to the same job opening in a new submission event
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Fiona Gallagher",
            email="fiona@southside.com",
        ),
        job_opening_id="JOB-RETAIL-101",
        is_new_application_submission=True,
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    assert result.status == RepeatApplicationStatus.REPEAT_APPLICATION_SAME_JOB
    assert result.is_repeat is True
    assert result.total_previous_applications == 1
    assert result.previous_applications[0].job_opening_id == "JOB-RETAIL-101"
    assert result.previous_applications[0].is_same_job is True


@pytest.mark.asyncio
async def test_multiple_previous_applications_across_distinct_jobs(
    repeat_service: RepeatApplicationService,
) -> None:
    doc1 = str(uuid4())
    doc2 = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc1,
            candidate_name="George Costanza",
            email="george@vandelay.com",
            job_opening_id="JOB-ARCHITECT",
            job_title="Architect",
        ),
        CandidateIdentityRecord(
            document_id=doc2,
            candidate_name="George Costanza",
            email="george@vandelay.com",
            job_opening_id="JOB-LATEX-SALES",
            job_title="Latex Salesman",
        ),
    ]
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="George Costanza",
            email="george@vandelay.com",
        ),
        job_opening_id="JOB-MARINE-BIOLOGIST",
        job_title="Marine Biologist",
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    assert result.status == RepeatApplicationStatus.MULTIPLE_PREVIOUS_APPLICATIONS
    assert result.is_repeat is True
    assert result.total_previous_applications == 2


@pytest.mark.asyncio
async def test_multiple_previous_applications_same_and_different_jobs(
    repeat_service: RepeatApplicationService,
) -> None:
    doc1 = str(uuid4())
    doc2 = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc1,
            candidate_name="Hal Jordan",
            email="hal@corps.org",
            job_opening_id="JOB-PILOT",
        ),
        CandidateIdentityRecord(
            document_id=doc2,
            candidate_name="Hal Jordan",
            email="hal@corps.org",
            job_opening_id="JOB-GUARDIAN",
        ),
    ]
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Hal Jordan",
            email="hal@corps.org",
        ),
        job_opening_id="JOB-PILOT",
        is_new_application_submission=True,
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    assert result.status == RepeatApplicationStatus.MULTIPLE_PREVIOUS_APPLICATIONS
    assert result.is_repeat is True
    assert result.total_previous_applications == 2


# ==============================================================================
# 4. Rule 4: Avoid False Positives Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_multiple_resume_attachments_same_job_grouped_as_one(
    repeat_service: RepeatApplicationService,
) -> None:
    doc1 = str(uuid4())
    doc2 = str(uuid4())
    doc3 = str(uuid4())
    # Candidate submitted 3 resume attachments for the same job opening (JOB-ALPHA)
    existing = [
        CandidateIdentityRecord(
            document_id=doc1,
            candidate_name="Iris West",
            email="iris@centralcity.news",
            job_opening_id="JOB-ALPHA",
            zoho_attachment_id="ATT-1",
        ),
        CandidateIdentityRecord(
            document_id=doc2,
            candidate_name="Iris West",
            email="iris@centralcity.news",
            job_opening_id="JOB-ALPHA",
            zoho_attachment_id="ATT-2",
        ),
        CandidateIdentityRecord(
            document_id=doc3,
            candidate_name="Iris West",
            email="iris@centralcity.news",
            job_opening_id="JOB-ALPHA",
            zoho_attachment_id="ATT-3",
        ),
    ]
    # Ingesting candidate into JOB-BETA
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Iris West",
            email="iris@centralcity.news",
        ),
        job_opening_id="JOB-BETA",
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    # Must NOT count as 3 applications! All 3 documents for JOB-ALPHA group into 1 application.
    assert result.status == RepeatApplicationStatus.REPEAT_APPLICATION_DIFFERENT_JOB
    assert result.total_previous_applications == 1
    assert len(result.previous_applications) == 1
    assert set(result.previous_applications[0].document_ids) == {doc1, doc2, doc3}


@pytest.mark.asyncio
async def test_reprocessing_same_document_does_not_create_repeat_application(
    repeat_service: RepeatApplicationService,
) -> None:
    doc_id = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc_id,
            candidate_name="Jesse Pinkman",
            email="jesse@albuquerque.net",
            job_opening_id="JOB-CHEM-1",
        )
    ]
    # Reprocessing doc_id
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Jesse Pinkman",
            email="jesse@albuquerque.net",
            document_id=doc_id,
        ),
        job_opening_id="JOB-CHEM-1",
        document_id=doc_id,
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    # Reprocessing the document must NOT count as a repeat application event!
    assert result.status == RepeatApplicationStatus.FIRST_APPLICATION
    assert result.is_repeat is False
    assert result.total_previous_applications == 0


@pytest.mark.asyncio
async def test_reuploading_resume_to_existing_application_does_not_trigger_repeat(
    repeat_service: RepeatApplicationService,
) -> None:
    doc1 = str(uuid4())
    existing = [
        CandidateIdentityRecord(
            document_id=doc1,
            candidate_name="Kim Wexler",
            email="kim@hhmlaw.com",
            job_opening_id="JOB-LAW-100",
        )
    ]
    # Candidate uploads an updated version to the same job without creating a new application event
    inp = RepeatApplicationInput(
        candidate_input=CandidateIdentityInput(
            candidate_name="Kim Wexler",
            email="kim@hhmlaw.com",
        ),
        job_opening_id="JOB-LAW-100",
        is_new_application_submission=False,
    )
    result = await repeat_service.detect_repeat_application(inp, existing_records=existing)

    # Adding an attachment or updating resume within the same application is not a repeat application
    assert result.status == RepeatApplicationStatus.FIRST_APPLICATION
    assert result.is_repeat is False


# ==============================================================================
# 5. Dict Input & Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_raw_dict_input_support(repeat_service: RepeatApplicationService) -> None:
    payload = {
        "candidate_input": {
            "candidate_name": "Luke Skywalker",
            "email": "luke@rebel.org",
            "phone": "+1 650 234 5678",
        },
        "job_opening_id": "JOB-JEDI",
    }
    result = await repeat_service.detect_repeat_application(payload, existing_records=[])

    assert result.status == RepeatApplicationStatus.FIRST_APPLICATION
    assert result.current_job_opening_id == "JOB-JEDI"
    assert result.is_repeat is False
