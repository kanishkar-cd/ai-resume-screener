from uuid import uuid4

import pytest

from app.db.session import AsyncSessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.ranking_repository import RankingRepository
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.document import DocumentCreate, DocumentType
from app.schemas.extracted_info import ExtractedResumeCreate
from app.schemas.project import ProjectCreate
from app.schemas.ranking import CandidateRankingCreate, RankingSortField, RankingSortOrder
from app.schemas.scoring import CandidateScoreCreate, ComponentScoreDetail, ComponentScores, RecommendationLevel, WeightedScores


def _score(document_id, project_id, score):
    detail = ComponentScoreDetail(score=score, explanation="test")
    return CandidateScoreCreate(document_id=document_id, project_id=project_id, component_scores=ComponentScores(skills=detail, experience=detail, projects=detail, education=detail, certifications=detail, languages=detail), weighted_scores=WeightedScores(skills=score * .4, experience=score * .25, projects=score * .15, education=score * .1, certifications=score * .05, languages=score * .05), raw_total_score=score, weighted_total_score=score, penalty_total=0, bonus_total=0, final_score=score, confidence=score, recommendation=RecommendationLevel.SHORTLIST if score >= 85 else RecommendationLevel.REVIEW, weight_config_version=1)


@pytest.mark.asyncio(loop_scope="session")
async def test_ranking_repository_upsert_search_filters_statistics_and_history() -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        projects, documents = ProjectRepository(session), DocumentRepository(session)
        extractions, scores, rankings = ExtractionRepository(session), ScoringRepository(session), RankingRepository(session)
        project = await projects.create(ProjectCreate(title=f"Rank {marker}", target_role="Engineer"))
        docs, score_models = [], []
        for index, (name, value) in enumerate((("Jane Doe", 90), ("John Roe", 70))):
            suffix = f"{marker}{index}"
            document = await documents.create(DocumentCreate(project_id=project.id, document_type=DocumentType.RESUME, original_filename=f"{suffix}.txt", stored_filename=f"{suffix}.txt", file_path=f"projects/{project.id}/resumes/{suffix}.txt", file_size_bytes=1, mime_type="text/plain", file_hash=suffix.ljust(64, "0")[:64]))
            await extractions.create_or_update_resume(ExtractedResumeCreate(document_id=document.id, candidate_name=name, email=f"{name.split()[0].lower()}@example.com"))
            docs.append(document); score_models.append(await scores.upsert_score(_score(document.id, project.id, value)))
        first = [CandidateRankingCreate(document_id=docs[i].id, candidate_score_id=score_models[i].id, rank_position=i + 1, percentile=100 - i * 50, final_score=90 - i * 20, recommendation=score_models[i].recommendation.value, confidence=90 - i * 20) for i in range(2)]
        assert await rankings.bulk_upsert_rankings(project.id, first)
        rows, total = await rankings.list_rankings(project.id, {"recommendation": RecommendationLevel.SHORTLIST, "min_score": 80, "max_score": None, "is_knocked_out": False}, "jane", 1, 20, RankingSortField.SCORE, RankingSortOrder.DESC)

        assert total == 1 and rows[0]["candidate_name"] == "Jane Doe"
        stats = await rankings.get_project_statistics(project.id)
        assert stats["total_candidates"] == 2 and stats["average_score"] == 80
        assert stats["highest_score"] == 90 and stats["lowest_score"] == 70 and stats["average_confidence"] == 80
        second = [CandidateRankingCreate(document_id=docs[1-i].id, candidate_score_id=score_models[1-i].id, rank_position=i + 1, percentile=100 - i * 50, final_score=70 + i * 20, recommendation=score_models[1-i].recommendation.value, confidence=70 + i * 20, previous_rank=2-i, rank_change=(2-i)-(i+1)) for i in range(2)]
        assert await rankings.bulk_upsert_rankings(project.id, second)
        leaders = await rankings.get_top_n_leaderboard(project.id, 1)
        assert leaders[0]["document_id"] == docs[1].id and leaders[0]["previous_rank"] == 2 and leaders[0]["rank_change"] == 1
        assert await rankings.bulk_upsert_rankings(project.id, [])
        for document in docs: await documents.delete_document(document.id)
        await projects.soft_delete(project.id)
