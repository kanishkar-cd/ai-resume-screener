from uuid import uuid4
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio(loop_scope="session")
async def test_recruiter_document_delete_and_reupload_lifecycle(async_client: AsyncClient) -> None:
    marker = uuid4().hex

    # 1. Create Project
    proj_resp = await async_client.post(
        "/api/v1/projects",
        json={"title": f"Lifecycle Test Project {marker}", "target_role": "Backend Developer"},
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["data"]["id"]

    # Initialize weight configuration for project
    weight_resp = await async_client.post(
        f"/api/v1/projects/{project_id}/weight-config",
        json={},
    )
    assert weight_resp.status_code == 201

    # 2. Upload Job Description
    jd_content = f"Python FastAPI PostgreSQL Backend Developer Job Description {marker}".encode()
    jd_resp = await async_client.post(
        f"/api/v1/projects/{project_id}/job-description",
        files={"file": ("jd.txt", jd_content, "text/plain")},
    )
    assert jd_resp.status_code == 201
    jd_id = jd_resp.json()["data"]["document_id"]

    # 3. Upload Resume
    resume_content = f"Alice Smith {marker}\nalice_{marker}@example.com\nPython FastAPI Backend Engineer".encode()
    res_resp = await async_client.post(
        f"/api/v1/projects/{project_id}/resumes/batch",
        files=[("files", ("resume.txt", resume_content, "text/plain"))],
    )
    assert res_resp.status_code == 207
    res_data = res_resp.json()["data"]
    assert res_data["successful_count"] == 1
    resume_id = res_data["successful_uploads"][0]["document_id"]

    # 4. Parse JD & Resume
    await async_client.post(f"/api/v1/documents/{jd_id}/parse")
    await async_client.post(f"/api/v1/documents/{resume_id}/parse")

    # 5. Extract JD & Resume
    await async_client.post(f"/api/v1/documents/{jd_id}/extract")
    await async_client.post(f"/api/v1/documents/{resume_id}/extract")

    # 6. Normalize JD & Resume
    await async_client.post(f"/api/v1/documents/{jd_id}/normalize")
    await async_client.post(f"/api/v1/documents/{resume_id}/normalize")

    # 7. Score
    score_resp = await async_client.post(f"/api/v1/projects/{project_id}/score")
    assert score_resp.status_code == 200

    # 8. Rank
    rank_resp = await async_client.post(f"/api/v1/projects/{project_id}/rankings")
    assert rank_resp.status_code == 200

    # 9. Delete Resume via API
    del_res_resp = await async_client.delete(f"/api/v1/projects/{project_id}/resumes/{resume_id}")
    assert del_res_resp.status_code == 204

    # Verify resume list is now empty
    list_res = await async_client.get(f"/api/v1/projects/{project_id}/resumes")
    assert list_res.status_code == 200
    assert list_res.json()["data"]["total"] == 0

    # 10. Re-upload SAME Resume -> MUST succeed without duplicate document conflict!
    reupload_res_resp = await async_client.post(
        f"/api/v1/projects/{project_id}/resumes/batch",
        files=[("files", ("resume.txt", resume_content, "text/plain"))],
    )
    assert reupload_res_resp.status_code == 207
    new_res_data = reupload_res_resp.json()["data"]
    assert new_res_data["successful_count"] == 1
    new_resume_id = new_res_data["successful_uploads"][0]["document_id"]

    # 11. Execute full pipeline again for new resume
    await async_client.post(f"/api/v1/documents/{new_resume_id}/parse")
    await async_client.post(f"/api/v1/documents/{new_resume_id}/extract")
    await async_client.post(f"/api/v1/documents/{new_resume_id}/normalize")
    await async_client.post(f"/api/v1/projects/{project_id}/score")
    new_rank_resp = await async_client.post(f"/api/v1/projects/{project_id}/rankings")
    assert new_rank_resp.status_code == 200

    # 12. Delete Job Description via API
    del_jd_resp = await async_client.delete(f"/api/v1/projects/{project_id}/job-description")
    assert del_jd_resp.status_code == 204

    # 13. Re-upload SAME Job Description -> MUST succeed!
    reupload_jd_resp = await async_client.post(
        f"/api/v1/projects/{project_id}/job-description",
        files={"file": ("jd.txt", jd_content, "text/plain")},
    )
    assert reupload_jd_resp.status_code == 201
    new_jd_id = reupload_jd_resp.json()["data"]["document_id"]

    # 14. Execute pipeline again for new JD
    await async_client.post(f"/api/v1/documents/{new_jd_id}/parse")
    await async_client.post(f"/api/v1/documents/{new_jd_id}/extract")
    await async_client.post(f"/api/v1/documents/{new_jd_id}/normalize")
    await async_client.post(f"/api/v1/projects/{project_id}/score")
    final_rank_resp = await async_client.post(f"/api/v1/projects/{project_id}/rankings")
    assert final_rank_resp.status_code == 200
