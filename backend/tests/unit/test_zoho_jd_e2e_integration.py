"""
End-to-End Zoho Job Description Integration Tests (Phase 3 Validation)
=======================================================================
Verifies:
1. Zoho API -> HTML Normalization -> Storage -> Extraction -> Normalization -> API Response.
2. Representative Zoho JD with HTML tags, bullet lists, special characters, and headings.
3. Edge cases: Empty description, missing required skills, broken HTML.
4. Repeated Zoho JD import (replaces prior JD, no orphan active documents).
5. Error handling: Non-existent project, unconfigured Zoho credentials.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.document import DocumentModel, DocumentTypeEnum, ProcessingStatusEnum
from app.db.session import engine
from app.services.extractors.ai_jd_extractor import AIJDExtractor
from app.services.zoho_recruit_service import ZohoJobOpening, ZohoRecruitClient


@pytest.fixture(autouse=True)
async def mock_ai_extractor(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_JD_EXTRACTION", "false")
    with (
        patch("app.services.jd_extraction_service.AIJDExtractor.extract", AsyncMock(return_value=None)),
        patch.object(AIJDExtractor, "extract", AsyncMock(return_value=None)),
    ):
        yield
    await engine.dispose()


@pytest.fixture
def representative_zoho_job() -> ZohoJobOpening:
    return ZohoJobOpening(
        id="zoho-lead-dev-777",
        posting_title="Lead Python & Cloud Architect",
        job_opening_id="REQ_777",
        department="Platform Engineering",
        required_skills="Python, FastAPI, AWS, Docker, Kubernetes &amp; PostgreSQL",
        job_description="""
        <h2>About the Position</h2>
        <p>We are searching for a <strong>Lead Python &amp; Cloud Architect</strong> to drive our backend platform.</p>
        
        <h3>Key Responsibilities:</h3>
        <ul>
            <li>Architect scalable microservices using Python &amp; FastAPI.</li>
            <li>Deploy and maintain cloud infrastructure on AWS &amp; Kubernetes.</li>
            <li>Implement automated CI/CD pipelines and container orchestration.</li>
            <li>Mentor engineering team members &amp; conduct rigorous code reviews.</li>
        </ul>

        <h3>Requirements &amp; Qualifications:</h3>
        <ul>
            <li>Bachelor&#39;s or Master&#39;s degree in Computer Science or related engineering field.</li>
            <li>5+ years of software engineering and cloud infrastructure experience.</li>
            <li>Deep proficiency with PostgreSQL, Docker, Redis &amp; messaging queues.</li>
        </ul>
        """,
        job_status="In-progress",
        city="San Francisco",
    )


@pytest.mark.asyncio
async def test_e2e_representative_zoho_jd_import(representative_zoho_job) -> None:
    """Test full pipeline: HTML normalization -> text assembly -> parsing -> extraction -> normalization."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create target project
        proj_resp = await client.post(
            "/api/v1/projects",
            json={
                "title": "E2E Zoho Import Project",
                "target_role": "Lead Architect",
                "department": "Platform Engineering",
            },
        )
        assert proj_resp.status_code == 201
        proj_data = proj_resp.json()
        project_id = proj_data["data"]["id"] if "data" in proj_data else proj_data["id"]

        try:
            # 2. Mock Zoho Recruit Client
            with (
                patch.object(ZohoRecruitClient, "configured", True),
                patch.object(
                    ZohoRecruitClient,
                    "get_job_opening",
                    AsyncMock(return_value=representative_zoho_job),
                ),
            ):
                import_resp = await client.post(
                    f"/api/v1/projects/{project_id}/zoho/import-jd",
                    json={"job_id": representative_zoho_job.id},
                )
                assert import_resp.status_code == 200
                res_body = import_resp.json()
                data = res_body["data"] if "data" in res_body else res_body

                # Verify Response Contract
                assert data["project_id"] == project_id
                assert data["document_id"] is not None
                assert "Zoho_JD_zoho-lead-dev-777" in data["filename"]
                assert data["processing_status"] == "COMPLETED"
                assert data["processing_stage"] in ["COMPLETED", "NORMALIZATION"]

                # Verify Extracted Content (Clean, No raw HTML tags or unescaped entities)
                extracted = data["extracted"]
                assert extracted is not None
                assert extracted["job_title"] is not None
                assert "Lead" in extracted["job_title"] or "Architect" in extracted["job_title"] or "Python" in extracted["job_title"]

                # Skills must contain normalized items
                skills = extracted.get("required_skills") or extracted.get("skills") or []
                skills_lower = [s.lower() for s in skills]
                assert any("python" in s for s in skills_lower)
                assert any("aws" in s or "fastapi" in s or "docker" in s for s in skills_lower)

                # Responsibilities extracted from <li> bullets
                responsibilities = extracted.get("responsibilities") or []
                assert len(responsibilities) >= 1
                assert not any("<li>" in r or "</li>" in r for r in responsibilities)
                assert not any("&amp;" in r or "&#39;" in r for r in responsibilities)

                # Education & Experience extracted
                assert extracted.get("education") is not None
                assert extracted.get("experience") is not None

                # Verify Normalized Output
                assert data.get("normalized") is not None

                # Verify /documents/{doc_id}/extracted can retrieve it
                doc_id = data["document_id"]
                get_extracted = await client.get(f"/api/v1/documents/{doc_id}/extracted")
                assert get_extracted.status_code == 200
                get_data = get_extracted.json()
                get_extracted_obj = get_data.get("data") or get_data
                assert get_extracted_obj["id"] is not None
        finally:
            # Cleanup project
            await client.delete(f"/api/v1/projects/{project_id}")


@pytest.mark.asyncio
async def test_zoho_jd_import_empty_and_missing_sections() -> None:
    """Test importing Zoho JD with empty description, missing skills, and broken HTML."""
    sparse_zoho_job = ZohoJobOpening(
        id="zoho-sparse-111",
        posting_title="Junior QA Specialist",
        job_opening_id=None,
        department=None,
        required_skills="",
        job_description="<div><b>Broken HTML without closing tags<p>Simple description.",
        job_status="Open",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        proj_resp = await client.post(
            "/api/v1/projects",
            json={"title": "Sparse JD Project", "target_role": "QA"},
        )
        assert proj_resp.status_code == 201
        proj_data = proj_resp.json()
        project_id = proj_data["data"]["id"] if "data" in proj_data else proj_data["id"]

        try:
            with (
                patch.object(ZohoRecruitClient, "configured", True),
                patch.object(
                    ZohoRecruitClient,
                    "get_job_opening",
                    AsyncMock(return_value=sparse_zoho_job),
                ),
            ):
                import_resp = await client.post(
                    f"/api/v1/projects/{project_id}/zoho/import-jd",
                    json={"job_id": sparse_zoho_job.id},
                )
                assert import_resp.status_code == 200
                res_body = import_resp.json()
                data = res_body["data"] if "data" in res_body else res_body
                assert data["processing_status"] == "COMPLETED"
                assert data["extracted"] is not None
        finally:
            await client.delete(f"/api/v1/projects/{project_id}")


@pytest.mark.asyncio
async def test_repeated_zoho_jd_import_soft_deletes_prior() -> None:
    """Test that importing a new Zoho JD into the same project replaces the prior active JD."""
    job1 = ZohoJobOpening(
        id="job-1",
        posting_title="Version 1 JD",
        job_description="Initial description.",
        required_skills="Python",
    )
    job2 = ZohoJobOpening(
        id="job-2",
        posting_title="Version 2 JD",
        job_description="Updated description.",
        required_skills="Python, Go",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        proj_resp = await client.post(
            "/api/v1/projects",
            json={"title": "Repeated Import Project", "target_role": "Engineer"},
        )
        proj_data = proj_resp.json()
        project_id = proj_data["data"]["id"] if "data" in proj_data else proj_data["id"]

        try:
            with (
                patch.object(ZohoRecruitClient, "configured", True),
                patch.object(ZohoRecruitClient, "get_job_opening") as mock_get,
            ):
                # First import
                mock_get.return_value = job1
                resp1 = await client.post(
                    f"/api/v1/projects/{project_id}/zoho/import-jd",
                    json={"job_id": job1.id},
                )
                assert resp1.status_code == 200
                res1_data = resp1.json()
                doc1_id = (res1_data["data"] if "data" in res1_data else res1_data)["document_id"]

                # Second import into same project
                mock_get.return_value = job2
                resp2 = await client.post(
                    f"/api/v1/projects/{project_id}/zoho/import-jd",
                    json={"job_id": job2.id},
                )
                assert resp2.status_code == 200
                res2_data = resp2.json()
                doc2_id = (res2_data["data"] if "data" in res2_data else res2_data)["document_id"]
                assert doc1_id != doc2_id

                # List documents for project: only doc2 should be active JD
                list_resp = await client.get(f"/api/v1/documents?project_id={project_id}&document_type=JOB_DESCRIPTION")
                assert list_resp.status_code == 200
                list_body = list_resp.json()
                items = (list_body["data"] if "data" in list_body else list_body).get("items", [])
                active_jd_docs = [
                    d for d in items
                    if d.get("document_type") == "JOB_DESCRIPTION"
                ]
                assert len(active_jd_docs) == 1
                assert active_jd_docs[0]["id"] == doc2_id
        finally:
            await client.delete(f"/api/v1/projects/{project_id}")


@pytest.mark.asyncio
async def test_zoho_jd_import_unconfigured_error() -> None:
    """Test importing Zoho JD returns 503 when client credentials are not configured."""
    fake_project_id = str(uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(ZohoRecruitClient, "configured", False):
            resp = await client.post(
                f"/api/v1/projects/{fake_project_id}/zoho/import-jd",
                json={"job_id": "any-job"},
            )
            assert resp.status_code == 503
