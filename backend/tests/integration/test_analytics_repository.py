from uuid import uuid4

import pytest

from app.db.session import AsyncSessionLocal
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import DocumentCreate, DocumentType
from app.schemas.insights import CandidateInsightCreate
from app.schemas.project import ProjectCreate


@pytest.mark.asyncio(loop_scope="session")
async def test_analytics_repository_insight_upsert_and_pipeline_counts() -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        projects, documents, analytics = ProjectRepository(session), DocumentRepository(session), AnalyticsRepository(session)
        project = await projects.create(ProjectCreate(title=f"Insights {marker}", target_role="Engineer"))
        document = await documents.create(DocumentCreate(project_id=project.id, document_type=DocumentType.RESUME, original_filename=f"{marker}.txt", stored_filename=f"{marker}.txt", file_path=f"projects/{project.id}/resumes/{marker}.txt", file_size_bytes=1, mime_type="text/plain", file_hash=marker.ljust(64, "0")[:64]))
        payload = CandidateInsightCreate(document_id=document.id, project_id=project.id, summary="Initial", score_explanation="Score", recommendation_reason="Reason")
        created = await analytics.get_or_create_insight(document.id, payload)
        updated = await analytics.get_or_create_insight(document.id, payload.model_copy(update={"summary": "Updated"}))
        assert created.id == updated.id and updated.summary == "Updated"
        counts = await analytics.get_pipeline_stage_counts(project.id)
        assert counts.total_candidates == 1 and counts.candidates_ingested == 1 and counts.candidates_scored == 0
        await documents.delete_document(document.id)
        await projects.soft_delete(project.id)
