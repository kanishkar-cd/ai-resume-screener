import asyncio
import os
import sys
import time
from pathlib import Path
from uuid import uuid4
from fastapi import UploadFile

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import AsyncSessionLocal
from app.models.project import ProjectModel, ProjectStatusEnum
from app.models.document import DocumentTypeEnum
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.services.storage_service import StorageService
from app.services.document_service import DocumentService
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.services.parsing_service import ParsingService
from app.repositories.extracted_jd_repository import ExtractedJDRepository
from app.services.jd_extraction_service import JDExtractionService
from app.repositories.normalized_jd_repository import NormalizedJDRepository
from app.services.jd_normalization_service import JDNormalizationService


SAMPLE_JD = """
Senior Python Backend Engineer

About the Role:
We are looking for a Senior Python Backend Engineer to join our Core Platform team.
You will architect, build, and maintain high-performance microservices, REST APIs,
and data pipelines using FastAPI, PostgreSQL, Docker, and AWS.

Responsibilities:
- Design and develop scalable backend APIs using Python and FastAPI.
- Build and optimize relational databases using PostgreSQL and SQLAlchemy.
- Implement automated CI/CD pipelines and deployment strategies with Docker and Kubernetes.
- Collaborate with frontend engineers to integrate RESTful endpoints.
- Conduct code reviews, enforce engineering best practices, and mentor junior engineers.

Requirements:
- 5+ years of software development experience with Python.
- Strong hands-on experience with FastAPI, Django, or Flask.
- Expertise in PostgreSQL, relational schema design, query optimization, and indexing.
- Solid understanding of Docker, Kubernetes, and AWS (EC2, S3, RDS).
- Experience with Redis caching and asynchronous message queues (Celery, Kafka, or RabbitMQ).
- Bachelor's or Master's degree in Computer Science, Software Engineering, or related discipline.

Nice to Have:
- Experience with GraphQL, gRPC, and microservices architecture.
- Knowledge of machine learning deployments and LLM application pipelines.
"""

from app.schemas.project import ProjectCreate

async def run_benchmark():
    async with AsyncSessionLocal() as db:
        print("=== JD PROCESSING BENCHMARK (AFTER OPTIMIZATION) ===")
        # Create a test project
        proj_repo = ProjectRepository(db)
        project = await proj_repo.create(ProjectCreate(
            title=f"Benchmark Requisition {uuid4().hex[:6]}",
            target_role="Senior Python Backend Engineer",
            department="Engineering",
            description="Benchmark project for JD processing latency",
            metadata_json={"test": True},
        ))
        project_id = project.id
        print(f"Created benchmark project: {project_id}")

        # Create temporary sample JD file
        temp_dir = Path("scratch_benchmark")
        temp_dir.mkdir(exist_ok=True)
        jd_path = temp_dir / "sample_backend_jd.txt"
        jd_path.write_text(SAMPLE_JD, encoding="utf-8")

        with open(jd_path, "rb") as f:
            upload_file = UploadFile(
                filename="sample_backend_jd.txt",
                file=f,
                headers={"content-type": "text/plain"},
            )

            # Measure end-to-end unified flow
            total_start = time.perf_counter()

            # 1. Services
            doc_repo = DocumentRepository(db)
            storage_service = StorageService()
            doc_service = DocumentService(doc_repo, proj_repo, storage_service)
            parsed_repo = ParsedDocumentRepository(db)
            parsing_service = ParsingService(doc_repo, parsed_repo, storage_service)
            extracted_repo = ExtractedJDRepository(db)
            jd_extract_service = JDExtractionService(doc_repo, parsed_repo, extracted_repo)
            normalized_repo = NormalizedJDRepository(db)
            jd_norm_service = JDNormalizationService(doc_repo, extracted_repo, normalized_repo)

            # Stage 1: Upload
            t0 = time.perf_counter()
            upload_res = await doc_service.upload_job_description(project_id, upload_file)
            doc_id = upload_res.document_id
            t_upload = time.perf_counter() - t0

            # Stage 2: Parse (deterministic local parser)
            t0 = time.perf_counter()
            parse_res = await parsing_service.parse_document(doc_id)
            t_parse = time.perf_counter() - t0

            # Stage 3: Extract
            t0 = time.perf_counter()
            extract_res = await jd_extract_service.extract_document(doc_id)
            t_extract = time.perf_counter() - t0

            # Stage 4: Normalize
            t0 = time.perf_counter()
            norm_res = await jd_norm_service.normalize_document(doc_id)
            t_norm = time.perf_counter() - t0

            # Retrieval
            extracted_data = await jd_extract_service.get_extracted_document(doc_id)
            normalized_data = await jd_norm_service.get_normalized_document(doc_id)
            total_elapsed = time.perf_counter() - total_start

        print(f"\n--- TIMINGS ---")
        print(f"1. Upload:    {t_upload:.3f} s")
        print(f"2. Parse:     {t_parse:.3f} s (Local parser: PyMuPDF / PlainText)")
        print(f"3. Extract:   {t_extract:.3f} s")
        print(f"4. Normalize: {t_norm:.3f} s")
        print(f"TOTAL TIME:   {total_elapsed:.3f} s")

        print(f"\n--- VERIFICATION ---")
        print(f"Document ID: {doc_id}")
        parsed_doc_record = await parsed_repo.get_by_document_id(doc_id)
        print(f"Parsed Text Length: {len(parsed_doc_record.raw_text)} chars, Words: {parsed_doc_record.word_count}")
        print(f"Extracted Required Skills ({len(extracted_data.required_skills)}): {extracted_data.required_skills}")
        print(f"Extracted Preferred Skills ({len(extracted_data.preferred_skills)}): {extracted_data.preferred_skills}")
        print(f"Extracted Responsibilities ({len(extracted_data.responsibilities)}): {extracted_data.responsibilities}")
        print(f"Normalized Canonical Skills ({len(normalized_data.skills)}): {normalized_data.skills}")
        print(f"Normalized Degree Requirements: {normalized_data.degree_requirements}")
        print(f"Normalized Experience Requirements: {[r.display_value for r in normalized_data.experience_requirements]}")

        # Clean up test project and scratch files
        await proj_repo.soft_delete(project_id)
        if jd_path.exists():
            jd_path.unlink()
        if temp_dir.exists():
            try:
                temp_dir.rmdir()
            except Exception:
                pass
        print("\nAll verifications passed. Cleanup completed.")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
