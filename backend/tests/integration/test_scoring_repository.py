from uuid import uuid4

import pytest

from app.db.session import AsyncSessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.document import DocumentCreate, DocumentType
from app.schemas.project import ProjectCreate
from app.schemas.scoring import (
    CandidateScoreCreate, ComponentScoreDetail, ComponentScores,
    RecommendationLevel, WeightedScores,
)


@pytest.mark.asyncio(loop_scope="session")
async def test_scoring_repository_upsert_queryable_columns_and_delete() -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        projects, documents, scores = ProjectRepository(session), DocumentRepository(session), ScoringRepository(session)
        project = await projects.create(ProjectCreate(title=f"Score {marker}", target_role="Engineer"))
        document = await documents.create(DocumentCreate(
            project_id=project.id, document_type=DocumentType.RESUME, original_filename=f"{marker}.txt",
            stored_filename=f"{marker}.txt", file_path=f"projects/{project.id}/resumes/{marker}.txt",
            file_size_bytes=1, mime_type="text/plain", file_hash=marker.ljust(64, "0")[:64],
        ))
        detail = ComponentScoreDetail(score=80, explanation="test")
        components = ComponentScores(skills=detail, experience=detail, projects=detail, education=detail, certifications=detail, languages=detail)
        data = CandidateScoreCreate(
            document_id=document.id, project_id=project.id, component_scores=components,
            weighted_scores=WeightedScores(skills=32, experience=20, projects=12, education=8, certifications=4, languages=4),
            raw_total_score=80, weighted_total_score=80, penalty_total=0, bonus_total=0,
            final_score=80, confidence=90, recommendation=RecommendationLevel.RECOMMENDED,
            weight_config_version=1,
        )
        created = await scores.upsert_score(data)
        updated = await scores.upsert_score(data.model_copy(update={"final_score": 85, "weight_config_version": 2}))
        assert created.id == updated.id and float(updated.skills_score) == 80
        assert float(updated.final_score) == 85 and updated.weight_config_version == 2
        assert len(await scores.get_project_scores(project.id)) == 1
        assert await scores.delete_project_scores(project.id)
        await documents.delete_document(document.id)
        await projects.soft_delete(project.id)
