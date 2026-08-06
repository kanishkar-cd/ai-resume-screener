from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.documents import get_document_service
from app.main import app
from app.schemas.document import (
    BatchResumeUploadRead,
    DocumentPaginatedResponse,
    DocumentRead,
    DocumentType,
    DocumentUploadRead,
    ProcessingStage,
    ProcessingStatus,
)


def upload_read(project_id: UUID, filename: str, document_type: DocumentType):
    return DocumentUploadRead(
        document_id=uuid4(),
        project_id=project_id,
        document_type=document_type,
        filename=filename,
        processing_stage=ProcessingStage.INGESTION,
        processing_status=ProcessingStatus.UPLOADED,
    )


class FakeRecruiterDocumentService:
    def __init__(self) -> None:
        self.job: DocumentUploadRead | None = None
        self.resumes: list[DocumentUploadRead] = []

    async def upload_job_description(self, project_id, file):
        self.job = upload_read(project_id, file.filename, DocumentType.JOB_DESCRIPTION)
        return self.job

    async def get_job_description(self, project_id):
        assert self.job is not None
        now = datetime.now(UTC)
        return DocumentRead(
            id=self.job.document_id,
            project_id=project_id,
            document_type=DocumentType.JOB_DESCRIPTION,
            original_filename=self.job.filename,
            file_size_bytes=12,
            mime_type="text/plain",
            file_hash="a" * 64,
            processing_stage=ProcessingStage.INGESTION,
            processing_status=ProcessingStatus.UPLOADED,
            metadata_json={},
            created_at=now,
            updated_at=now,
        )

    async def upload_resume_batch(self, project_id, files):
        self.resumes = [
            upload_read(project_id, file.filename, DocumentType.RESUME)
            for file in files
        ]
        return BatchResumeUploadRead(
            project_id=project_id,
            total_received=len(files),
            successful_count=len(files),
            failed_count=0,
            successful_uploads=self.resumes,
            failed_uploads=[],
        )

    async def list_project_resumes(self, project_id, *args):
        now = datetime.now(UTC)
        items = [
            DocumentRead(
                id=item.document_id,
                project_id=project_id,
                document_type=DocumentType.RESUME,
                original_filename=item.filename,
                file_size_bytes=12,
                mime_type="text/plain",
                file_hash="b" * 64,
                processing_stage=ProcessingStage.INGESTION,
                processing_status=ProcessingStatus.UPLOADED,
                metadata_json={},
                created_at=now,
                updated_at=now,
            )
            for item in self.resumes
        ]
        return DocumentPaginatedResponse(
            items=items,
            total=len(items),
            page=1,
            page_size=20,
            total_pages=1,
        )


@pytest.mark.asyncio
async def test_recruiter_workflow_and_multiple_file_picker(
    async_client: httpx.AsyncClient,
) -> None:
    service = FakeRecruiterDocumentService()
    app.dependency_overrides[get_document_service] = lambda: service
    project_id = uuid4()

    job = await async_client.post(
        f"/api/v1/projects/{project_id}/job-description",
        files={"file": ("job.txt", b"job description", "text/plain")},
    )
    assert job.status_code == 201
    fetched_job = await async_client.get(
        f"/api/v1/projects/{project_id}/job-description"
    )
    assert fetched_job.status_code == 200

    batch = await async_client.post(
        f"/api/v1/projects/{project_id}/resumes/batch",
        files=[
            ("files", ("alice.txt", b"Alice", "text/plain")),
            ("files", ("bob.txt", b"Bob", "text/plain")),
        ],
    )
    assert batch.status_code == 207
    assert batch.json()["data"]["successful_count"] == 2

    resumes = await async_client.get(f"/api/v1/projects/{project_id}/resumes")
    assert resumes.status_code == 200
    assert resumes.json()["data"]["total"] == 2

    schema = app.openapi()
    request_schema = schema["paths"][
        "/api/v1/projects/{project_id}/resumes/batch"
    ]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
    component = request_schema["$ref"].split("/")[-1]
    assert schema["components"]["schemas"][component]["properties"]["files"][
        "type"
    ] == "array"
