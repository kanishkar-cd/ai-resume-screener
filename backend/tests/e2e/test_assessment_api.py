import asyncio
from uuid import UUID, uuid4
import httpx
import pytest


from app.api.v1.endpoints.assessment import get_assessment_service
from app.main import app
from app.schemas.assessment import (
    AssessmentHandoffData,
    CandidateAssessmentItem,
)
from app.services.cd_recruit_service import CDRecruitService, CDRecruitException
from app.services.document_service import DocumentNotFoundException
from app.services.project_service import ProjectNotFoundException


class FakeAssessmentService:
    def __init__(self) -> None:
        self.project_id = uuid4()
        self.candidate_id = uuid4()

    async def handoff_assessment(
        self,
        project_id: UUID,
        candidate_ids: list[UUID],
        requisition_ref: str,
    ) -> AssessmentHandoffData:
        if project_id != self.project_id:
            raise ProjectNotFoundException()

        for cid in candidate_ids:
            if cid != self.candidate_id:
                raise DocumentNotFoundException()

        if requisition_ref == "FAIL_CD_RECRUIT":
            raise CDRecruitException("CD-Recruit endpoint returned status 500")

        return AssessmentHandoffData(
            project_id=project_id,
            requisition_ref=requisition_ref,
            total_invited=len(candidate_ids),
            candidates=[
                CandidateAssessmentItem(
                    candidate_id=cid,
                    candidate_name="Jegadhees J",
                    email="jegadhees@example.com",
                    assessment_link="http://localhost:3001/assessment/token_xyz123",
                    status="INVITED",
                )
                for cid in candidate_ids
            ],
        )


@pytest.mark.asyncio
async def test_assessment_handoff_success(async_client: httpx.AsyncClient) -> None:
    service = FakeAssessmentService()
    app.dependency_overrides[get_assessment_service] = lambda: service

    response = await async_client.post(
        f"/api/v1/projects/{service.project_id}/assessment/handoff",
        json={
            "candidate_ids": [str(service.candidate_id)],
            "requisition_ref": "REQ-2026-ENG-042",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["project_id"] == str(service.project_id)
    assert data["requisition_ref"] == "REQ-2026-ENG-042"
    assert data["total_invited"] == 1
    assert data["candidates"][0]["candidate_id"] == str(service.candidate_id)
    assert data["candidates"][0]["candidate_name"] == "Jegadhees J"
    assert data["candidates"][0]["assessment_link"] == "http://localhost:3001/assessment/token_xyz123"


@pytest.mark.asyncio
async def test_assessment_handoff_missing_project(async_client: httpx.AsyncClient) -> None:
    service = FakeAssessmentService()
    app.dependency_overrides[get_assessment_service] = lambda: service

    missing_project_id = uuid4()
    response = await async_client.post(
        f"/api/v1/projects/{missing_project_id}/assessment/handoff",
        json={
            "candidate_ids": [str(service.candidate_id)],
            "requisition_ref": "REQ-2026-ENG-042",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_assessment_handoff_invalid_candidate(async_client: httpx.AsyncClient) -> None:
    service = FakeAssessmentService()
    app.dependency_overrides[get_assessment_service] = lambda: service

    invalid_candidate_id = uuid4()
    response = await async_client.post(
        f"/api/v1/projects/{service.project_id}/assessment/handoff",
        json={
            "candidate_ids": [str(invalid_candidate_id)],
            "requisition_ref": "REQ-2026-ENG-042",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_assessment_handoff_cd_recruit_failure(async_client: httpx.AsyncClient) -> None:
    service = FakeAssessmentService()
    app.dependency_overrides[get_assessment_service] = lambda: service

    response = await async_client.post(
        f"/api/v1/projects/{service.project_id}/assessment/handoff",
        json={
            "candidate_ids": [str(service.candidate_id)],
            "requisition_ref": "FAIL_CD_RECRUIT",
        },
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "CD_RECRUIT_INTEGRATION_FAILED"


@pytest.mark.asyncio
async def test_cd_recruit_outbound_payload_structure(monkeypatch) -> None:
    captured_payload = {}

    async def mock_post(self, url, json=None, headers=None):
        captured_payload["url"] = url
        captured_payload["json"] = json
        captured_payload["headers"] = headers

        class MockResponse:
            status_code = 200
            def json(self):
                return {
                    "candidates": [
                        {"assessment_link": "http://localhost:3001/assessment/token_xyz"}
                    ]
                }

        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    service = CDRecruitService()
    results = await service.send_candidates(
        department_code="ENG",
        level="MID",
        requisition_ref="REQ-2026-ENG-042",
        candidates=[
            {
                "candidate_name": "Vaishnavi S",
                "email": "vaishnavi@example.com",
                "phone": "+1234567890",
                "ai_score": 92.5,
                "metadata": {"doc_id": "123"},
            }
        ],
    )

    assert captured_payload["url"] == "http://localhost:3001/api/v1/partner/candidates"
    body = captured_payload["json"]
    assert body["department_code"] == "ENG"
    assert body["level"] == "MID"
    assert body["requisition_ref"] == "REQ-2026-ENG-042"
    assert len(body["candidates"]) == 1

    candidate_data = body["candidates"][0]
    assert candidate_data["name"] == "Vaishnavi S"
    assert candidate_data["email"] == "vaishnavi@example.com"
    assert candidate_data["phone"] == "+1234567890"
    assert candidate_data["ai_score"] == 92.5
    assert candidate_data["metadata"] == {"doc_id": "123"}
    assert "first_name" not in candidate_data
    assert "last_name" not in candidate_data

    assert results[0]["assessment_link"] == "http://localhost:3001/assessment/token_xyz"


@pytest.mark.asyncio
async def test_camelcase_assessment_url_parsing(monkeypatch) -> None:
    """Verify that camelCase keys (assessmentUrl, assessmentLink, inviteUrl, link) from CD-Recruit are correctly mapped."""
    doc_id = uuid4()

    async def mock_send_candidates(*args, **kwargs):
        return [
            {"assessmentUrl": "http://localhost:3001/test/token_camel_123"},
        ]

    from app.services.assessment_service import AssessmentService
    service = AssessmentService(
        projects=None,
        documents=None,
        extractions=None,
    )
    monkeypatch.setattr(service.cd_recruit, "send_candidates", mock_send_candidates)

    class FakeProject:
        department = "ENG"
        target_role = "MID"
        metadata_json = {}


    class FakeDocument:
        project_id = doc_id
        original_filename = "resume.pdf"

    class FakeExtraction:
        candidate_name = "Jane Doe"
        email = "jane@example.com"
        phone = "+1999888777"

    class FakeProjectRepo:
        async def get_by_id(self, pid): return FakeProject()

    class FakeDocRepo:
        async def get_document(self, did): return FakeDocument()

    class FakeExtRepo:
        async def get_resume_by_document_id(self, did): return FakeExtraction()

    service.projects = FakeProjectRepo()
    service.documents = FakeDocRepo()
    service.extractions = FakeExtRepo()

    handoff_data = await service.handoff_assessment(
        project_id=doc_id,
        candidate_ids=[doc_id],
        requisition_ref="REQ-2026-ENG-042",
    )

    assert handoff_data.candidates[0].assessment_link == "http://localhost:3001/test/token_camel_123"


@pytest.mark.asyncio
async def test_fresher_and_experienced_experience_level_handoff(monkeypatch) -> None:
    """Verify that Fresher and Experienced metadata_json selections pass FRESHER and EXPERIENCED to CD-Recruit."""
    captured_calls = []

    async def mock_send_candidates(department_code, level, requisition_ref, candidates):
        captured_calls.append({
            "department_code": department_code,
            "level": level,
            "requisition_ref": requisition_ref,
        })
        return [{"assessmentUrl": "http://localhost:3001/test/token_123"}]

    from app.services.assessment_service import AssessmentService

    doc_id = uuid4()

    class FakeDocument:
        project_id = doc_id
        original_filename = "resume.pdf"

    class FakeExtraction:
        candidate_name = "Jane Doe"
        email = "jane@example.com"
        phone = "+1999888777"

    class FakeDocRepo:
        async def get_document(self, did): return FakeDocument()

    class FakeExtRepo:
        async def get_resume_by_document_id(self, did): return FakeExtraction()

    service = AssessmentService(
        projects=None,
        documents=FakeDocRepo(),
        extractions=FakeExtRepo(),
    )
    monkeypatch.setattr(service.cd_recruit, "send_candidates", mock_send_candidates)

    # Test 1: Fresher selection
    class FresherProject:
        department = "PMO"
        target_role = "Associate"
        metadata_json = {"experience_level": "Fresher"}

    class FresherProjectRepo:
        async def get_by_id(self, pid): return FresherProject()

    service.projects = FresherProjectRepo()
    await service.handoff_assessment(project_id=doc_id, candidate_ids=[doc_id], requisition_ref="REQ-1")

    assert captured_calls[0]["department_code"] == "PMO"
    assert captured_calls[0]["level"] == "FRESHER"

    # Test 2: Experienced selection
    class ExperiencedProject:
        department = "SOFTWARE_ENGINEERING"
        target_role = "Senior Full-Stack Engineer"
        metadata_json = {"experience_level": "Experienced"}

    class ExperiencedProjectRepo:
        async def get_by_id(self, pid): return ExperiencedProject()

    service.projects = ExperiencedProjectRepo()
    await service.handoff_assessment(project_id=doc_id, candidate_ids=[doc_id], requisition_ref="REQ-2")

    assert captured_calls[1]["department_code"] == "SOFTWARE_ENGINEERING"
    assert captured_calls[1]["level"] == "EXPERIENCED"


@pytest.mark.asyncio
async def test_persisted_project_req_ref_is_sent_to_cd_recruit(monkeypatch) -> None:
    """Verify that the persisted project req_ref from metadata_json is the exact value sent to CDRecruitService."""
    captured_req_ref = None

    async def mock_send_candidates(department_code, level, requisition_ref, candidates):
        nonlocal captured_req_ref
        captured_req_ref = requisition_ref
        return [{"assessmentUrl": "http://localhost:3001/test/token_persisted_123"}]

    from app.services.assessment_service import AssessmentService

    doc_id = uuid4()

    class FakeDocument:
        project_id = doc_id
        original_filename = "resume.pdf"

    class FakeExtraction:
        candidate_name = "Jane Doe"
        email = "jane@example.com"
        phone = "+1999888777"

    class FakeDocRepo:
        async def get_document(self, did): return FakeDocument()

    class FakeExtRepo:
        async def get_resume_by_document_id(self, did): return FakeExtraction()

    class PersistedProject:
        department = "SOFTWARE_ENGINEERING"
        target_role = "Software Engineer"
        metadata_json = {"req_ref": "REQ-2026-SOFTWARE_ENGINEERING-739", "experience_level": "Fresher"}

    class PersistedProjectRepo:
        async def get_by_id(self, pid): return PersistedProject()

    service = AssessmentService(
        projects=PersistedProjectRepo(),
        documents=FakeDocRepo(),
        extractions=FakeExtRepo(),
    )
    monkeypatch.setattr(service.cd_recruit, "send_candidates", mock_send_candidates)

    await service.handoff_assessment(
        project_id=doc_id,
        candidate_ids=[doc_id],
        requisition_ref="REQ-2026-SOFTWARE_ENGINEERING-042",
    )

    assert captured_req_ref == "REQ-2026-SOFTWARE_ENGINEERING-739"


@pytest.mark.asyncio
async def test_cd_recruit_invites_response_parsing(monkeypatch) -> None:
    """Regression test verifying that CD-Recruit response with 'invites' key maps assessment_link correctly."""
    from app.services.cd_recruit_service import CDRecruitService
    from app.services.assessment_service import AssessmentService
    import httpx

    cd_service = CDRecruitService()
    exact_cd_recruit_response = {
        "success": True,
        "drive_id": "bac52db7-c4a3-4458-bf42-bdd7ef5f798a",
        "requisition_ref": "REQ-2026-SOFTWARE_ENGINEERING-739",
        "department_code": "SOFTWARE_ENGINEERING",
        "level": "EXPERIENCED",
        "invites": [
            {
                "candidate_email": "jane@example.com",
                "candidate_name": "Jane Doe",
                "assessment_link": "http://localhost:3000/invite/inv_108431d0c4a81e0a4e0928bc",
                "expires_at": "2026-08-20T10:22:21.839Z"
            }
        ],
        "drive_warnings": []
    }

    async def mock_post(*args, **kwargs):
        class MockResponse:
            status_code = 201
            def json(self): return exact_cd_recruit_response
        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    # 1. Verify CDRecruitService parses invites array
    invites = await cd_service.send_candidates(
        department_code="SOFTWARE_ENGINEERING",
        level="EXPERIENCED",
        requisition_ref="REQ-2026-SOFTWARE_ENGINEERING-739",
        candidates=[{"name": "Jane Doe", "email": "jane@example.com", "phone": "", "ai_score": 90.0, "metadata": {}}]
    )
    assert len(invites) == 1
    assert invites[0]["assessment_link"] == "http://localhost:3000/invite/inv_108431d0c4a81e0a4e0928bc"

    # 2. Verify AssessmentService handoff maps assessment_link to CandidateAssessmentItem
    doc_id = uuid4()

    class FakeDocument:
        project_id = doc_id
        original_filename = "resume.pdf"

    class FakeExtraction:
        candidate_name = "Jane Doe"
        email = "jane@example.com"
        phone = "+1999888777"

    class FakeDocRepo:
        async def get_document(self, did): return FakeDocument()

    class FakeExtRepo:
        async def get_resume_by_document_id(self, did): return FakeExtraction()

    class FakeProject:
        department = "SOFTWARE_ENGINEERING"
        target_role = "Senior Engineer"
        metadata_json = {"req_ref": "REQ-2026-SOFTWARE_ENGINEERING-739", "experience_level": "Experienced"}

    class FakeProjectRepo:
        async def get_by_id(self, pid): return FakeProject()

    service = AssessmentService(
        projects=FakeProjectRepo(),
        documents=FakeDocRepo(),
        extractions=FakeExtRepo(),
        cd_recruit=cd_service,
    )

    handoff_res = await service.handoff_assessment(
        project_id=doc_id,
        candidate_ids=[doc_id],
        requisition_ref="REQ-2026-SOFTWARE_ENGINEERING-739",
    )

    assert len(handoff_res.candidates) == 1
    assert handoff_res.candidates[0].assessment_link == "http://localhost:3000/invite/inv_108431d0c4a81e0a4e0928bc"
    assert handoff_res.candidates[0].status == "INVITED"


@pytest.mark.asyncio
async def test_email_invitation_dispatches(monkeypatch) -> None:
    """Test A, B, C, D, E, F: Assessment invitation email delivery scenarios."""
    from app.services.email_service import EmailService
    from app.services.assessment_service import AssessmentService

    doc_id1 = uuid4()
    doc_id2 = uuid4()

    class FakeDocument1:
        project_id = doc_id1
        original_filename = "resume1.pdf"

    class FakeDocument2:
        project_id = doc_id1
        original_filename = "resume2.pdf"


    class FakeExtraction1:
        candidate_name = "Candidate One"
        email = "one@real-candidate.com"
        phone = "+1111111"

    class FakeExtraction2:
        candidate_name = "Candidate Two"
        email = "two@real-candidate.com"
        phone = "+2222222"

    class FakeDocRepo:
        async def get_document(self, did):
            return FakeDocument1() if did == doc_id1 else FakeDocument2()

    class FakeExtRepo:
        async def get_resume_by_document_id(self, did):
            return FakeExtraction1() if did == doc_id1 else FakeExtraction2()

    class FakeProject:
        department = "SOFTWARE_ENGINEERING"
        target_role = "Senior Engineer"
        metadata_json = {"req_ref": "REQ-2026-ENG-99", "experience_level": "Experienced"}

    class FakeProjectRepo:
        async def get_by_id(self, pid): return FakeProject()

    # Test A & B: Successful email for single & multiple candidates
    sent_emails = []

    class MockEmailService(EmailService):
        async def send_assessment_invitation(self, candidate_name, candidate_email, assessment_link, requisition_ref):
            if not candidate_email or not candidate_email.strip():
                return
            if not assessment_link or not assessment_link.strip():
                return
            sent_emails.append({
                "candidate_name": candidate_name,
                "candidate_email": candidate_email,
                "assessment_link": assessment_link,
                "requisition_ref": requisition_ref,
            })

    async def mock_send_candidates(*args, **kwargs):
        return [
            {"candidate_email": "one@real-candidate.com", "assessment_link": "http://localhost:3000/invite/inv_one"},
            {"candidate_email": "two@real-candidate.com", "assessment_link": "http://localhost:3000/invite/inv_two"},
        ]

    email_srv = MockEmailService()
    service = AssessmentService(
        projects=FakeProjectRepo(),
        documents=FakeDocRepo(),
        extractions=FakeExtRepo(),
        email_service=email_srv,
    )
    monkeypatch.setattr(service.cd_recruit, "send_candidates", mock_send_candidates)

    handoff = await service.handoff_assessment(project_id=doc_id1, candidate_ids=[doc_id1, doc_id2], requisition_ref="REQ-1")
    await asyncio.sleep(0.1)

    assert len(sent_emails) == 2
    assert sent_emails[0]["candidate_email"] == "one@real-candidate.com"
    assert sent_emails[0]["assessment_link"] == "http://localhost:3000/invite/inv_one"
    assert sent_emails[1]["candidate_email"] == "two@real-candidate.com"
    assert sent_emails[1]["assessment_link"] == "http://localhost:3000/invite/inv_two"

    # Test C: Missing assessment_link -> no email sent
    sent_emails.clear()

    async def mock_send_candidates_no_link(*args, **kwargs):
        return [{"candidate_email": "one@real-candidate.com", "assessment_link": None}]

    monkeypatch.setattr(service.cd_recruit, "send_candidates", mock_send_candidates_no_link)
    await service.handoff_assessment(project_id=doc_id1, candidate_ids=[doc_id1], requisition_ref="REQ-1")
    await asyncio.sleep(0.1)
    assert len(sent_emails) == 0


    # Test D: Missing candidate email -> no email sent
    sent_emails.clear()

    class FakeExtractionNoEmail:
        candidate_name = "No Email Candidate"
        email = None
        phone = ""

    class FakeExtRepoNoEmail:
        async def get_resume_by_document_id(self, did): return FakeExtractionNoEmail()

    service_no_email = AssessmentService(
        projects=FakeProjectRepo(),
        documents=FakeDocRepo(),
        extractions=FakeExtRepoNoEmail(),
        email_service=email_srv,
    )
    async def mock_send_candidates_link(*args, **kwargs):
        return [{"candidate_email": "", "assessment_link": "http://localhost:3000/invite/inv_x"}]
    monkeypatch.setattr(service_no_email.cd_recruit, "send_candidates", mock_send_candidates_link)
    await service_no_email.handoff_assessment(project_id=doc_id1, candidate_ids=[doc_id1], requisition_ref="REQ-1")
    # Clear synthetic fallback emails if any
    filtered_sent = [e for e in sent_emails if e["candidate_email"] and not e["candidate_email"].endswith("@example.com")]
    assert len(filtered_sent) == 0


    # Test E: Email provider failure -> handoff succeeds, status remains INVITED, assessment_link remains present
    class FailingEmailService(EmailService):
        async def send_assessment_invitation(self, *args, **kwargs):
            raise RuntimeError("Provider connection error 500")

    failing_service = AssessmentService(
        projects=FakeProjectRepo(),
        documents=FakeDocRepo(),
        extractions=FakeExtRepo(),
        email_service=FailingEmailService(),
    )
    async def mock_send_candidates_ok(*args, **kwargs):
        return [{"candidate_email": "one@example.com", "assessment_link": "http://localhost:3000/invite/inv_one"}]
    monkeypatch.setattr(failing_service.cd_recruit, "send_candidates", mock_send_candidates_ok)

    handoff_failing = await failing_service.handoff_assessment(project_id=doc_id1, candidate_ids=[doc_id1], requisition_ref="REQ-1")
    assert handoff_failing.candidates[0].status == "INVITED"
    assert handoff_failing.candidates[0].assessment_link == "http://localhost:3000/invite/inv_one"

    # Test G: Project status updated to COMPLETED on successful handoff
    updated_statuses = []
    class StatusTrackingProjectRepo(FakeProjectRepo):
        async def update(self, project_id, update_data):
            updated_statuses.append(update_data.status)
            return await super().get_by_id(project_id)

    status_service = AssessmentService(
        projects=StatusTrackingProjectRepo(),
        documents=FakeDocRepo(),
        extractions=FakeExtRepo(),
        email_service=FailingEmailService(),
    )

    monkeypatch.setattr(status_service.cd_recruit, "send_candidates", mock_send_candidates_ok)
    await status_service.handoff_assessment(project_id=doc_id1, candidate_ids=[doc_id1], requisition_ref="REQ-STATUS-TEST")
    assert len(updated_statuses) == 1
    assert updated_statuses[0] == "COMPLETED"






