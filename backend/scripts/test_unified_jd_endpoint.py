import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4
import io

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.session import AsyncSessionLocal
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate

SAMPLE_JD = """
DevOps & Cloud Engineer

About the Role:
We are seeking a DevOps Engineer with expertise in AWS, Docker, Kubernetes, CI/CD pipelines, and Terraform.

Responsibilities:
- Build and maintain continuous integration and continuous deployment pipelines using GitHub Actions.
- Manage containerized infrastructure using Docker and Kubernetes.
- Provision cloud resources using Terraform on AWS.

Requirements:
- 3+ years experience with Cloud Infrastructure (AWS or GCP).
- Hands-on experience with Docker and Kubernetes.
- Proficiency in Python or Bash scripting.
- Experience with PostgreSQL and Redis.
"""

async def test_endpoint():
    async with AsyncSessionLocal() as db:
        proj_repo = ProjectRepository(db)
        project = await proj_repo.create(ProjectCreate(
            title=f"DevOps Requisition {uuid4().hex[:6]}",
            target_role="DevOps Engineer",
            department="Cloud Engineering",
            description="Integration test for unified JD endpoint",
            metadata_json={"test": True},
        ))
        project_id = str(project.id)
        print(f"Created project: {project_id}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = {
            "file": ("devops_jd.txt", io.BytesIO(SAMPLE_JD.encode("utf-8")), "text/plain")
        }
        print("Sending POST /api/v1/projects/{project_id}/job-description/process ...")
        t_req0 = asyncio.get_event_loop().time()
        response = await client.post(
            f"/api/v1/projects/{project_id}/job-description/process",
            files=files,
        )
        t_req = (asyncio.get_event_loop().time() - t_req0) * 1000
        print(f"Status Code: {response.status_code} (Turnaround Time: {t_req:.2f} ms)")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()["data"]
        print(f"Document ID: {data['document_id']}")
        print(f"Filename: {data['filename']}")
        print(f"Processing Stage: {data['processing_stage']}")
        print(f"Processing Status: {data['processing_status']}")
        assert data["extracted"] is not None
        assert data["normalized"] is not None
        print(f"Extracted Skills Count: {len(data['extracted']['skills'])}")
        print(f"Extracted Required Skills: {data['extracted']['required_skills']}")
        print(f"Extracted Responsibilities: {data['extracted']['responsibilities']}")
        print(f"Normalized Canonical Skills ({len(data['normalized']['skills'])}): {data['normalized']['skills']}")
        print("\nUNIFIED ENDPOINT TEST SUCCEEDED 100%!")

    async with AsyncSessionLocal() as db:
        proj_repo = ProjectRepository(db)
        await proj_repo.soft_delete(project.id)
        print("Project cleaned up.")

if __name__ == "__main__":
    asyncio.run(test_endpoint())
