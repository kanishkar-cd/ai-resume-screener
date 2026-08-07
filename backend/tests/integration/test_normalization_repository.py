from uuid import uuid4

import pytest

from app.db.session import AsyncSessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import DocumentCreate, DocumentType
from app.schemas.extracted_info import ExtractedResumeCreate
from app.schemas.project import ProjectCreate
from app.services.normalization_service import NormalizationService


@pytest.mark.asyncio(loop_scope="session")
async def test_normalized_resume_upsert_persists_canonical_jsonb() -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        projects, documents = ProjectRepository(session), DocumentRepository(session)
        extractions, normalizations = ExtractionRepository(session), NormalizationRepository(session)
        project = await projects.create(ProjectCreate(title=f"Normalize {marker}", target_role="Engineer"))
        document = await documents.create(DocumentCreate(
            project_id=project.id, document_type=DocumentType.RESUME,
            original_filename=f"{marker}.txt", stored_filename=f"{marker}.txt",
            file_path=f"projects/{project.id}/resumes/{marker}.txt", file_size_bytes=1,
            mime_type="text/plain", file_hash=marker.ljust(64, "0")[:64],
        ))
        extracted = await extractions.create_or_update_resume(ExtractedResumeCreate(
            document_id=document.id, email="JANE@EXAMPLE.COM", phone="+91-98765-43210",
            designation="C++ Developer", skills=["Py", "postgres"],
            education=[{"degree": "B.E.", "year": "2020"}], companies=["Acme Corp."],
        ))
        service = NormalizationService(documents, extractions, normalizations)
        await service.normalize_document_data(document.id)
        first = await normalizations.get_resume_by_document_id(document.id)
        await service.normalize_document_data(document.id)
        second = await normalizations.get_resume_by_document_id(document.id)
        parent = await documents.get_document(document.id)
        assert first is not None and second is not None and first.id == second.id
        assert first.skills == ["Python", "PostgreSQL"]
        assert first.education[0]["degree"] == "Bachelor of Engineering"
        assert first.email == "jane@example.com" and first.phone == "+919876543210"
        assert first.ruleset_version == "1.0.0"
        assert parent.processing_stage.value == "COMPLETED"
        assert await normalizations.delete_resume_by_document_id(document.id)
        await documents.delete_document(document.id)
        await projects.soft_delete(project.id)
