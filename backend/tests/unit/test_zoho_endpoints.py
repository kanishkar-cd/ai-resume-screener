from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.zoho_recruit_service import ZohoJobOpening, ZohoJobWithResumes, ZohoRecruitClient


@pytest.fixture
def mock_zoho_jobs():
    return [
        ZohoJobOpening(
            id="5001",
            posting_title="Senior Python Backend Engineer",
            job_opening_id="JOB_101",
            job_description="FastAPI & Python expert.",
            required_skills="Python, FastAPI, Postgres",
            job_status="In-progress",
            target_date="2026-11-01",
            city="Bengaluru",
            department="Engineering",
            modified_time="2026-10-01T08:00:00+05:30",
        ),
        ZohoJobOpening(
            id="5002",
            posting_title="Frontend Developer",
            job_opening_id="JOB_102",
            job_description="React developer.",
            required_skills="React, TypeScript",
            job_status="Open",
            target_date="2026-12-01",
            city="Remote",
            department="Frontend",
            modified_time="2026-10-02T08:00:00+05:30",
        ),
    ]


@pytest.mark.asyncio
async def test_zoho_status_endpoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/zoho/status")
        assert response.status_code == 200
        data = response.json()
        assert "configured" in data
        assert "accounts_url" in data
        assert "api_url" in data


@pytest.mark.asyncio
async def test_zoho_job_openings_endpoint(mock_zoho_jobs) -> None:
    async def fake_iter(*args, **kwargs):
        for job in mock_zoho_jobs:
            yield job

    with (
        patch.object(ZohoRecruitClient, "configured", True),
        patch.object(ZohoRecruitClient, "iter_job_openings", side_effect=fake_iter),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/zoho/job-openings")
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 2
            assert body["items"][0]["id"] == "5001"
            assert body["items"][0]["posting_title"] == "Senior Python Backend Engineer"


@pytest.mark.asyncio
async def test_zoho_single_job_opening_endpoint(mock_zoho_jobs) -> None:
    with (
        patch.object(ZohoRecruitClient, "configured", True),
        patch.object(ZohoRecruitClient, "get_job_opening", AsyncMock(return_value=mock_zoho_jobs[0])),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/zoho/job-openings/5001")
            assert response.status_code == 200
            body = response.json()
            assert body["id"] == "5001"
            assert body["posting_title"] == "Senior Python Backend Engineer"
            assert body["required_skills"] == "Python, FastAPI, Postgres"
