"""
Runtime trace test — verifies the complete extraction pipeline
for the Shri Harini Karthika resume from POST /parse through GET /extracted.

Prints every intermediate object so any field-drop between steps is visible.

Run: python -m pytest tests/e2e/test_extraction_runtime_trace.py -s -v
"""
import json
import uuid
from collections.abc import AsyncGenerator
from io import BytesIO

import httpx
import pytest
import pytest_asyncio

from app.main import app


RESUME_TEXT = b"""Shri Harini Karthika
sasikumar80989705@gmail.com
9043652396
Coimbatore

EDUCATION
Bachelor of Technology in Artificial Intelligence and Data Science
Rathinam Technical Campus
9.0 CGPA

INTERSHIP
Customer Centria, Coimbatore
Role : Database Management Intern
Three Months Internship
08/2025 - 10/2025
- Managed cloud databases and SQL querying.

PROJECTS
Project: Event Registering Portal (AWS Cloud)
- Built serverless web app using Lambda, API Gateway, S3, and DynamoDB.
Project: Devops-Based Ecommerce Website
- Deployed microservices using Docker, Jenkins, and Terraform.

CERTIFICATIONS
MongoDB
Azure DP-900
Overview Of Geographical
Information System (IIRS)
AWS Academy Cloud Foundations
Hackathon (Techgium)

TECHNICAL SKILLS
Python, SQL, AWS, Lambda, API Gateway, S3, DynamoDB, Docker, Jenkins, Terraform
"""


@pytest_asyncio.fixture
async def trace_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _pp(label: str, data: object) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2, default=str))


@pytest.mark.asyncio
async def test_full_extraction_runtime_trace(trace_client: httpx.AsyncClient) -> None:
    # ------------------------------------------------------------------ #
    # STEP 1 — Create project
    # ------------------------------------------------------------------ #
    proj_r = await trace_client.post("/api/v1/projects", json={"title": "TraceTest", "target_role": "Software Engineer"})
    assert proj_r.status_code == 201, f"project create failed: {proj_r.text}"
    project_id = proj_r.json()["data"]["id"]

    # ------------------------------------------------------------------ #
    # STEP 2 — Upload resume as a .txt file
    # ------------------------------------------------------------------ #
    upload_r = await trace_client.post(
        f"/api/v1/projects/{project_id}/resumes/batch",
        files=[("files", ("shri_harini.txt", BytesIO(RESUME_TEXT), "text/plain"))],
    )
    assert upload_r.status_code == 207, f"upload failed: {upload_r.text}"
    document_id = upload_r.json()["data"]["successful_uploads"][0]["document_id"]
    print(f"\n[STEP 2] document_id = {document_id}")

    # ------------------------------------------------------------------ #
    # STEP 3 — Parse
    # ------------------------------------------------------------------ #
    parse_r = await trace_client.post(f"/api/v1/documents/{document_id}/parse")
    assert parse_r.status_code in (200, 202), f"parse failed: {parse_r.text}"
    print(f"[STEP 3] parse status = {parse_r.status_code}")

    # ------------------------------------------------------------------ #
    # STEP 4 — GET parsed — confirm normalized_text content
    # ------------------------------------------------------------------ #
    parsed_r = await trace_client.get(f"/api/v1/documents/{document_id}/parsed")
    assert parsed_r.status_code == 200, f"get parsed failed: {parsed_r.text}"
    parsed_data = parsed_r.json()["data"]
    print(f"\n[STEP 4] normalized_text (first 800 chars):")
    print(repr(parsed_data["normalized_text"][:800]))
    print(f"[STEP 4] word_count = {parsed_data['word_count']}")
    print(f"[STEP 4] character_count = {parsed_data['character_count']}")

    # ------------------------------------------------------------------ #
    # STEP 5 — Run extract
    # ------------------------------------------------------------------ #
    extract_r = await trace_client.post(f"/api/v1/documents/{document_id}/extract")
    print(f"\n[STEP 5] POST /extract status = {extract_r.status_code}")
    print(f"[STEP 5] POST /extract body = {extract_r.text}")
    assert extract_r.status_code == 200, f"extract failed: {extract_r.text}"

    # ------------------------------------------------------------------ #
    # STEP 6 — GET extracted — the actual runtime output
    # ------------------------------------------------------------------ #
    extracted_r = await trace_client.get(f"/api/v1/documents/{document_id}/extracted")
    assert extracted_r.status_code == 200, f"get extracted failed: {extracted_r.text}"
    data = extracted_r.json()["data"]

    _pp("STEP 6A — experience[] from GET /extracted", data.get("experience", []))
    _pp("STEP 6B — companies[] from GET /extracted", data.get("companies", []))
    _pp("STEP 6C — projects[] from GET /extracted", data.get("projects", []))
    _pp("STEP 6D — certifications[] from GET /extracted", data.get("certifications", []))
    _pp("STEP 6E — confidence_scores from GET /extracted", data.get("confidence_scores", {}))
    _pp("STEP 6F — raw_metadata from GET /extracted", data.get("raw_metadata", {}))

    # ------------------------------------------------------------------ #
    # STEP 7 — Acceptance criteria assertions
    # ------------------------------------------------------------------ #
    experience = data.get("experience", [])
    companies = data.get("companies", [])
    projects = data.get("projects", [])
    certifications = data.get("certifications", [])
    confidence = data.get("confidence_scores", {})

    print("\n" + "="*60)
    print("  STEP 7 — Acceptance Criteria Checks")
    print("="*60)

    # Experience
    assert len(experience) >= 1, f"FAIL: experience is empty. Got: {experience}"
    exp0 = experience[0]
    assert exp0.get("company") == "Customer Centria", f"FAIL: company = {exp0.get('company')!r}"
    assert "Database Management Intern" in (exp0.get("designation") or exp0.get("title") or ""), \
        f"FAIL: designation = {exp0.get('designation')!r}"
    assert exp0.get("employment_type") == "Internship", f"FAIL: employment_type = {exp0.get('employment_type')!r}"
    assert exp0.get("start_date") == "08/2025", f"FAIL: start_date = {exp0.get('start_date')!r}"
    assert exp0.get("end_date") == "10/2025", f"FAIL: end_date = {exp0.get('end_date')!r}"
    print("[PASS] experience[0] — company, designation, employment_type, start_date, end_date")

    # Companies
    assert "Customer Centria" in companies, f"FAIL: companies = {companies}"
    print("[PASS] companies = ['Customer Centria']")

    # Projects
    assert len(projects) == 2, f"FAIL: expected 2 projects, got {len(projects)}: {[p.get('name') for p in projects]}"
    project_names = [p.get("name", "") for p in projects]
    assert any("Event Registering Portal" in n for n in project_names), \
        f"FAIL: Event Registering Portal missing. Got: {project_names}"
    assert any("Devops-Based Ecommerce Website" in n for n in project_names), \
        f"FAIL: Devops-Based Ecommerce Website missing. Got: {project_names}"
    print("[PASS] projects — 2 projects with correct names")

    # Certifications
    cert_set = set(certifications)
    assert "MongoDB" in cert_set, f"FAIL: MongoDB missing. Got: {certifications}"
    assert "Azure DP-900" in cert_set, f"FAIL: Azure DP-900 missing. Got: {certifications}"
    assert any("Overview Of Geographical Information System" in c for c in certifications), \
        f"FAIL: IIRS cert missing. Got: {certifications}"
    assert "AWS Academy Cloud Foundations" in cert_set, f"FAIL: AWS Academy missing. Got: {certifications}"
    assert "Hackathon (Techgium)" in cert_set, f"FAIL: Hackathon missing. Got: {certifications}"
    print("[PASS] certifications — all 5 entries present")

    # Confidence
    assert confidence.get("experience", 0) > 0, f"FAIL: confidence.experience = {confidence.get('experience')}"
    assert confidence.get("companies", 0) > 0, f"FAIL: confidence.companies = {confidence.get('companies')}"
    print("[PASS] confidence_scores.experience > 0")
    print("[PASS] confidence_scores.companies > 0")

    print("\n[ALL ACCEPTANCE CRITERIA PASSED]")
