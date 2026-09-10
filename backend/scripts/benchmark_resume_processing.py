"""
Issue #4 - Resume Processing Latency Benchmark & Micro-Timing Profiler.
Runs a realistic batch of 5 production PDF candidate resumes through the current
Resume Processing flow without modifying any application code.
Collects microsecond-accurate timings for:
1. File upload/save
2. Affinda extraction per resume / local fallback
3. Extraction & persistence
4. Normalization & persistence
5. Frontend post-normalization profile fetch round-trips
6. Deterministic 0-50 scoring (Skills)
7. AI 0-50 scoring (Responsibilities via Groq)
8. Concurrency / queue scheduler / rate limiting
9. DB queries, commits, and session overhead
10. Final candidate ranking, persistence & listing
"""

import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

# Windows UTF-8 stdout
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import structlog

# Issue #4A instrumentation: capture per-resume Groq/Cerebras routing telemetry
# (resume_llm_routing_telemetry events emitted by SmartMatchEvaluator.evaluate)
# without touching any scoring/matching code. Non-matching events pass through untouched.
GROQ_TELEMETRY_EVENTS: list[dict] = []


def _capture_llm_telemetry(_logger, _method_name, event_dict):
    if event_dict.get("event") == "resume_llm_routing_telemetry":
        GROQ_TELEMETRY_EVENTS.append(dict(event_dict))
    return event_dict


structlog.configure(
    processors=[_capture_llm_telemetry, structlog.dev.ConsoleRenderer(colors=False)],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

from fastapi import UploadFile
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models import (
    DocumentModel,
    DocumentTypeEnum,
    ProjectModel,
    WeightConfigModel,
)
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.ranking_repository import RankingRepository
from app.repositories.scoring_repository import ScoringRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.project import ProjectCreate
from app.services.affinda_service import AffindaService
from app.services.document_service import DocumentService
from app.services.extraction_service import ExtractionService
from app.services.normalization_service import NormalizationService
from app.services.parsing_service import ParsingService
from app.services.ranking_service import RankingService
from app.services.scoring_service import ScoringEngineFacade
from app.services.storage_service import StorageService


SAMPLE_RESUME_FILES = [
    {
        "filename": "23cs196_Yogeshwar_R_1390.pdf",
        "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\7b215fd1-406c-4a6d-94ed-5fce8cc1ea86.pdf",
        "candidate": "Yogeshwar R",
    },
    {
        "filename": "Harshini_resume.pdf",
        "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\a034674d-5ea5-4051-be94-993e2e22bf5d.pdf",
        "candidate": "Harshini",
    },
    {
        "filename": "shri ram resume.pdf",
        "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\a31dd8a4-e910-4bb0-b2cb-596f3a7b7c5e.pdf",
        "candidate": "Shri Ram",
    },
    {
        "filename": "NAVEENA_N_RESUME.pdf",
        "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\cf1516cc-c28b-481d-bf5a-3038c0ec20b6.pdf",
        "candidate": "Naveena N",
    },
    {
        "filename": "23EC052- JEGADHEES J(RESUME) (1)_5572.pdf",
        "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\df94d3bf-ea62-48f2-a8ac-98c7c847742f.pdf",
        "candidate": "Jegadhees J",
    },
]

SAMPLE_JD_TEXT = """
Job Title: Software Engineer - Python & Cloud Backend
Location: Remote / Chennai, India
Department: Software Engineering
Experience Level: 0-2 Years

About the Role:
We are looking for a Software Engineer to design, build, and maintain high-performance backend systems and APIs.

Key Responsibilities:
- Design and develop robust RESTful APIs and backend microservices using Python.
- Integrate relational and NoSQL databases, write efficient SQL queries, and optimize database transactions.
- Implement CI/CD pipelines, containerize applications with Docker, and deploy services on AWS or GCP.
- Collaborate with frontend teams, review code, and maintain comprehensive API documentation.
- Monitor application performance, troubleshoot production issues, and ensure system security.

Required Technical Skills:
- Python, FastAPI, or Django
- PostgreSQL, SQL, Database Design
- Git, GitHub, Version Control
- REST API Design, JSON
- Docker, Containerization

Preferred Skills:
- Cloud Platforms (AWS, Azure, or GCP)
- Redis, Caching
- Unit Testing, Pytest, CI/CD
"""


async def main():
    print("=" * 80)
    print("ISSUE #4: RESUME PROCESSING LATENCY BENCHMARK")
    print("=" * 80)

    settings = get_settings()
    print(f"PostgreSQL Server : {settings.POSTGRES_SERVER}")
    print(f"Groq Model        : {settings.GROQ_MODEL}")
    print(f"Groq TPM Limit    : {settings.GROQ_TPM_LIMIT}")
    print(f"Affinda Configured: {bool(settings.AFFINDA_API_KEY and settings.AFFINDA_WORKSPACE_ID)}")
    print(f"Max Concurrent Resumes in Queue: {getattr(settings, 'MAX_CONCURRENT_RESUMES', 1)}")
    print(f"Batch Throttle Sec: {getattr(settings, 'LLM_BATCH_THROTTLE_SECONDS', 0.25)}")
    print("-" * 80)

    # 1. Create a dedicated test project and upload JD
    print("\n[STEP 1] Setting up benchmark project and Job Description...")
    project_id = uuid4()
    async with AsyncSessionLocal() as session:
        proj_repo = ProjectRepository(session)
        project = await proj_repo.create(
            ProjectCreate(
                title=f"Benchmark-Resumes-{project_id.hex[:6]}",
                department_code="SOFTWARE_ENGINEERING",
                hiring_level="EXPERIENCED",
                target_role="Software Engineer",
                description="Issue 4 Benchmark Project",
            )
        )
        project_id = project.id

    # Process JD into project
    async with AsyncSessionLocal() as session:
        from app.api.v1.endpoints.project_documents import process_job_description
        jd_file = UploadFile(
            filename="software_engineer_jd.txt",
            file=io.BytesIO(SAMPLE_JD_TEXT.encode("utf-8")),
            headers={"content-type": "text/plain"},
        )
        await process_job_description(project_id, jd_file, session)
        print(f"  Project Created: {project_id}")
        print("  Active Normalized JD ready.")

    # 2. Benchmark Stage 1: Batch Resume Upload
    print("\n[STEP 2] Benchmarking Resume Batch Upload (POST /projects/{id}/resumes/batch)...")
    upload_files = []
    for item in SAMPLE_RESUME_FILES:
        with open(item["path"], "rb") as f:
            content = f.read()
        upload_files.append(
            UploadFile(
                filename=item["filename"],
                file=io.BytesIO(content),
                headers={"content-type": "application/pdf"},
            )
        )

    t_batch_upload_start = perf_counter()
    per_resume_upload_timings = []

    async with AsyncSessionLocal() as session:
        storage = StorageService()
        doc_repo = DocumentRepository(session)
        proj_repo = ProjectRepository(session)
        doc_service = DocumentService(doc_repo, proj_repo, storage)

        t_proj_verify_0 = perf_counter()
        await doc_service._verify_project(project_id)
        t_proj_verify = (perf_counter() - t_proj_verify_0) * 1000

        uploaded_docs = []
        for uf in upload_files:
            t_doc_start = perf_counter()

            # sub-timing 1: disk save
            t0 = perf_counter()
            uf.file.seek(0)
            from app.services.document_service import validate_file
            orig_name, ext = await validate_file(uf)
            stored_name, file_path, size, file_hash = await storage.save_file(
                uf, project_id, "resumes", ext
            )
            t_disk = (perf_counter() - t0) * 1000

            # sub-timing 2: hash check DB query
            t0 = perf_counter()
            dup = await doc_repo.get_by_hash(project_id, file_hash, DocumentTypeEnum.RESUME)
            t_hash_db = (perf_counter() - t0) * 1000

            # sub-timing 3: create (flush only -- deferred to one batched commit below,
            # matching the fix applied to DocumentService.upload_resume_batch())
            t0 = perf_counter()
            from app.schemas.document import DocumentCreate, DocumentType
            created = await doc_repo.create(
                DocumentCreate(
                    project_id=project_id,
                    document_type=DocumentType.RESUME,
                    original_filename=orig_name,
                    stored_filename=stored_name,
                    file_path=file_path,
                    file_size_bytes=size,
                    mime_type="application/pdf",
                    file_hash=file_hash,
                ),
                commit=False,
                refresh=False,
            )
            t_create_db = (perf_counter() - t0) * 1000
            uploaded_docs.append(created)

            total_doc_upload = (perf_counter() - t_doc_start) * 1000
            per_resume_upload_timings.append({
                "filename": orig_name,
                "size_bytes": size,
                "disk_io_ms": t_disk,
                "hash_check_db_ms": t_hash_db,
                "create_commit_db_ms": t_create_db,
                "total_upload_ms": total_doc_upload,
                "document_id": created.id,
            })

        if uploaded_docs:
            t0 = perf_counter()
            await session.commit()
            print(f"  Single batched commit for {len(uploaded_docs)} resumes: {(perf_counter() - t0) * 1000:.2f} ms")

    total_batch_upload_ms = (perf_counter() - t_batch_upload_start) * 1000
    print(f"  Batch upload completed: {len(uploaded_docs)} resumes in {total_batch_upload_ms:.2f} ms")
    for r in per_resume_upload_timings:
        print(f"    - {r['filename']:<40} | Disk: {r['disk_io_ms']:6.2f}ms | Hash DB: {r['hash_check_db_ms']:6.2f}ms | Create DB: {r['create_commit_db_ms']:6.2f}ms | Total: {r['total_upload_ms']:6.2f}ms")

    # 3. Benchmark Stage 2: Parsing per Resume (Affinda vs Local Fallback)
    # NOTE: the backend exposes only a single-document parse endpoint (no
    # project/batch-level parse route), so there is no production code path to
    # call here directly. Each resume below still gets its own AsyncSessionLocal()
    # (the same one-session-per-task pattern ScoringEngineFacade.score_project()
    # already uses in production), so running them concurrently via asyncio.gather
    # is safe and demonstrates the latency win a future batch endpoint could reuse.
    print("\n[STEP 3] Benchmarking Resume Parsing (POST /documents/{id}/parse, concurrently per resume)...")
    t_batch_parse_start = perf_counter()

    async def _parse_one(r_meta: dict) -> dict:
        doc_id = r_meta["document_id"]
        t_parse_start = perf_counter()
        async with AsyncSessionLocal() as session:
            doc_repo = DocumentRepository(session)
            parsed_repo = ParsedDocumentRepository(session)
            storage = StorageService()
            affinda = AffindaService()
            parse_service = ParsingService(doc_repo, parsed_repo, storage, affinda)

            t0 = perf_counter()
            doc = await parse_service._load_document(doc_id)
            t_load_db = (perf_counter() - t0) * 1000

            path = storage.resolve_file(doc.file_path)

            t0 = perf_counter()
            from app.schemas.document import ProcessingStatus
            await parse_service._set_status(doc_id, ProcessingStatus.PARSING_PENDING, {}, document=doc, refresh=False)
            t_status_pending_db = (perf_counter() - t0) * 1000

            # Measure Affinda call
            t0 = perf_counter()
            affinda_error = None
            affinda_payload = None
            try:
                affinda_payload = await parse_service._try_affinda(doc, path)
            except Exception as e:
                affinda_error = str(e)
            t_affinda = (perf_counter() - t0) * 1000

            # Measure local fallback if Affinda was None
            local_fallback_ms = 0.0
            if affinda_payload is None:
                t0 = perf_counter()
                from asyncio import to_thread
                from app.services.parsers import parse_document_file
                from app.services.parsers.base import text_metrics
                parsed = await to_thread(parse_document_file, path, doc.mime_type)
                word_count, character_count = text_metrics(parsed.raw_text)
                local_fallback_ms = (perf_counter() - t0) * 1000
            else:
                raw_text = affinda_payload["data"].get("rawText", "")
                word_count, character_count = len(raw_text.split()), len(raw_text)
                from app.schemas.parsed_document import ParserEngine
                from app.services.parsers.base import ParseOutput
                parsed = ParseOutput(raw_text=raw_text, page_count=None, parser_engine=ParserEngine.PLAIN_TEXT, original_parser="AFFINDA")

            # Upsert parsed doc & status update
            t0 = perf_counter()
            from app.schemas.parsed_document import ParsedDocumentCreate
            await parsed_repo.upsert(
                ParsedDocumentCreate(
                    document_id=doc_id,
                    raw_text=parsed.raw_text,
                    normalized_text=parsed.raw_text,
                    page_count=parsed.page_count,
                    word_count=word_count,
                    character_count=character_count,
                    parser_engine=parsed.parser_engine,
                    parsing_duration_ms=round((perf_counter() - t_parse_start) * 1000, 3),
                ),
                commit=False,
                refresh=False,
            )
            await parse_service._set_status(doc_id, ProcessingStatus.PARSED, {"affinda_payload": parse_service._persistable_affinda_payload(affinda_payload)}, refresh=False, document=doc)
            t_save_db = (perf_counter() - t0) * 1000

            total_parse = (perf_counter() - t_parse_start) * 1000
            return {
                "filename": r_meta["filename"],
                "doc_id": doc_id,
                "db_pre_ms": t_load_db + t_status_pending_db,
                "affinda_ms": t_affinda,
                "affinda_success": affinda_payload is not None,
                "local_fallback_ms": local_fallback_ms,
                "db_save_ms": t_save_db,
                "total_parse_ms": total_parse,
                "word_count": word_count,
            }

    parsing_timings = list(await asyncio.gather(*[_parse_one(r_meta) for r_meta in per_resume_upload_timings]))
    total_batch_parse_ms = (perf_counter() - t_batch_parse_start) * 1000
    print(f"  Parsing completed in {total_batch_parse_ms:.2f} ms")
    for r in parsing_timings:
        print(f"    - {r['filename']:<40} | Affinda: {r['affinda_ms']:7.2f}ms ({'OK' if r['affinda_success'] else 'FALLBACK'}) | Local FB: {r['local_fallback_ms']:6.2f}ms | DB IO: {r['db_pre_ms']+r['db_save_ms']:6.2f}ms | Total: {r['total_parse_ms']:7.2f}ms")

    # 4. Benchmark Stage 3: Extraction per Resume (no batch extraction endpoint
    # exists either; same safe one-session-per-resume concurrency pattern as above)
    print("\n[STEP 4] Benchmarking Resume Extraction (POST /documents/{id}/extract, concurrently per resume)...")
    t_batch_extract_start = perf_counter()

    async def _extract_one(r_meta: dict) -> dict:
        doc_id = r_meta["document_id"]
        t_extract_start = perf_counter()
        async with AsyncSessionLocal() as session:
            doc_repo = DocumentRepository(session)
            parsed_repo = ParsedDocumentRepository(session)
            ext_repo = ExtractionRepository(session)
            ext_service = ExtractionService(doc_repo, parsed_repo, ext_repo)

            # DB reads
            t0 = perf_counter()
            doc = await ext_service._get_document(doc_id)
            parsed = await parsed_repo.get_by_document_id(doc_id)
            from app.schemas.document import ProcessingStage, ProcessingStatus
            await doc_repo.update_processing(doc_id, ProcessingStage.EXTRACTION, ProcessingStatus.IN_PROGRESS, document=doc, refresh=False)
            t_extract_db_read = (perf_counter() - t0) * 1000

            # Extraction logic (Affinda vs Regex/AI)
            t0 = perf_counter()
            extracted = await ext_service._affinda_resume(doc, parsed.normalized_text)
            affinda_map_ms = (perf_counter() - t0) * 1000
            ai_extract_ms = 0.0
            regex_extract_ms = 0.0

            if extracted is None:
                t0 = perf_counter()
                from app.services.extractors import ResumeExtractor
                deterministic = ResumeExtractor().extract(parsed.normalized_text)
                regex_extract_ms = (perf_counter() - t0) * 1000

                t0 = perf_counter()
                ai_extracted = None
                try:
                    ai_extracted = await ext_service.ai_resume_extractor.extract(parsed.normalized_text)
                except Exception:
                    pass
                ai_extract_ms = (perf_counter() - t0) * 1000
                from app.services.extractors.resume_merge import merge_resume_extractions
                extracted = merge_resume_extractions(deterministic, ai_extracted)

            # DB persistence
            t0 = perf_counter()
            from app.schemas.extracted_info import ExtractedResumeCreate
            await ext_repo.create_or_update_resume(ExtractedResumeCreate(document_id=doc_id, **extracted), commit=False, refresh=False)
            await doc_repo.update_processing(doc_id, ProcessingStage.COMPLETED, ProcessingStatus.COMPLETED, document=doc, refresh=False)
            t_extract_db_write = (perf_counter() - t0) * 1000

            total_extract = (perf_counter() - t_extract_start) * 1000
            return {
                "filename": r_meta["filename"],
                "db_read_ms": t_extract_db_read,
                "affinda_map_ms": affinda_map_ms,
                "regex_extract_ms": regex_extract_ms,
                "ai_extract_ms": ai_extract_ms,
                "db_write_ms": t_extract_db_write,
                "total_extract_ms": total_extract,
            }

    extraction_timings = list(await asyncio.gather(*[_extract_one(r_meta) for r_meta in per_resume_upload_timings]))
    total_batch_extract_ms = (perf_counter() - t_batch_extract_start) * 1000
    print(f"  Extraction completed in {total_batch_extract_ms:.2f} ms")
    for r in extraction_timings:
        print(f"    - {r['filename']:<40} | Affinda Map: {r['affinda_map_ms']:6.2f}ms | Regex: {r['regex_extract_ms']:6.2f}ms | AI Extract: {r['ai_extract_ms']:6.2f}ms | DB: {r['db_read_ms']+r['db_write_ms']:6.2f}ms | Total: {r['total_extract_ms']:7.2f}ms")

    # 5. Benchmark Stage 4: Normalization per Resume (no batch normalization
    # endpoint exists either; same safe one-session-per-resume concurrency pattern)
    print("\n[STEP 5] Benchmarking Resume Normalization (POST /documents/{id}/normalize, concurrently per resume)...")
    t_batch_norm_start = perf_counter()

    async def _normalize_one(r_meta: dict) -> dict:
        doc_id = r_meta["document_id"]
        t_norm_start = perf_counter()
        async with AsyncSessionLocal() as session:
            doc_repo = DocumentRepository(session)
            ext_repo = ExtractionRepository(session)
            norm_repo = NormalizationRepository(session)
            norm_service = NormalizationService(doc_repo, ext_repo, norm_repo)

            t0 = perf_counter()
            doc = await norm_service._get_document(doc_id)
            extracted = await norm_service._get_extracted(doc)
            from app.schemas.document import ProcessingStage, ProcessingStatus
            await doc_repo.update_processing(doc_id, ProcessingStage.NORMALIZATION, ProcessingStatus.IN_PROGRESS, document=doc, refresh=False)
            t_norm_db_read = (perf_counter() - t0) * 1000

            t0 = perf_counter()
            affinda_values = (getattr(extracted, "raw_metadata", {}) or {}).get("affinda_normalized_profile")
            from app.services.normalizers import ResumeNormalizer
            values = affinda_values or ResumeNormalizer().normalize(extracted)
            norm_compute_ms = (perf_counter() - t0) * 1000

            t0 = perf_counter()
            from app.schemas.normalized_info import NormalizedResumeCreate
            await norm_repo.create_or_update_resume(NormalizedResumeCreate(document_id=doc_id, extracted_resume_id=extracted.id, **values), commit=False, refresh=False)
            await doc_repo.update_processing(doc_id, ProcessingStage.COMPLETED, ProcessingStatus.COMPLETED, document=doc, refresh=False)
            t_norm_db_write = (perf_counter() - t0) * 1000

            total_norm = (perf_counter() - t_norm_start) * 1000
            return {
                "filename": r_meta["filename"],
                "db_read_ms": t_norm_db_read,
                "norm_compute_ms": norm_compute_ms,
                "db_write_ms": t_norm_db_write,
                "total_norm_ms": total_norm,
            }

    normalization_timings = list(await asyncio.gather(*[_normalize_one(r_meta) for r_meta in per_resume_upload_timings]))
    total_batch_norm_ms = (perf_counter() - t_batch_norm_start) * 1000
    print(f"  Normalization completed in {total_batch_norm_ms:.2f} ms")
    for r in normalization_timings:
        print(f"    - {r['filename']:<40} | Norm Compute: {r['norm_compute_ms']:6.2f}ms | DB IO: {r['db_read_ms']+r['db_write_ms']:6.2f}ms | Total: {r['total_norm_ms']:6.2f}ms")

    # 6. Benchmark Stage 5: Frontend Profile Fetching (Simulated)
    print("\n[STEP 6] Benchmarking Frontend Post-Normalization Profile Fetches...")
    t_fe_fetches_start = perf_counter()
    fe_fetch_timings = []
    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        ext_repo = ExtractionRepository(session)
        norm_repo = NormalizationRepository(session)

        for r_meta in per_resume_upload_timings:
            doc_id = r_meta["document_id"]
            t0 = perf_counter()
            d = await doc_repo.get_document(doc_id)
            n = await norm_repo.get_resume_by_document_id(doc_id)
            e = await ext_repo.get_resume_by_document_id(doc_id)
            fe_doc_fetch = (perf_counter() - t0) * 1000
            fe_fetch_timings.append({"filename": r_meta["filename"], "fetch_ms": fe_doc_fetch})

    total_fe_fetches_ms = (perf_counter() - t_fe_fetches_start) * 1000
    print(f"  Frontend profile queries (15 SELECT round-trips total): {total_fe_fetches_ms:.2f} ms")

    # 7. Benchmark Stage 6: Scoring (POST /projects/{id}/score)
    print("\n[STEP 7] Benchmarking Scoring Engine (POST /projects/{id}/score)...")
    print("  Evaluating Deterministic Skills (0-50) & AI Responsibilities (0-50 via Groq)...")

    scoring_sub_timings = []
    t_score_stage_start = perf_counter()

    async with AsyncSessionLocal() as session:
        proj_repo = ProjectRepository(session)
        doc_repo = DocumentRepository(session)
        norm_repo = NormalizationRepository(session)
        ext_repo = ExtractionRepository(session)
        score_repo = ScoringRepository(session)
        weight_repo = WeightConfigRepository(session)

        scoring_facade = ScoringEngineFacade(
            proj_repo, doc_repo, norm_repo, ext_repo, score_repo, weight_repo
        )

        # Measure Context Loading DB round trips
        t0 = perf_counter()
        job = await scoring_facade._load_project_context(project_id)
        weight_config = await weight_repo.get_by_project_id(project_id)
        resumes, _ = await doc_repo.list_resumes_by_project(project_id, 1, 10000)
        doc_ids = [d.id for d in resumes]
        norm_models = await norm_repo.get_resumes_by_document_ids(doc_ids)
        ext_models = await ext_repo.get_resumes_by_document_ids(doc_ids)
        t_scoring_context_db = (perf_counter() - t0) * 1000
        print(f"  Scoring Context DB Preloading: {t_scoring_context_db:.2f} ms")

        norm_map = {n.document_id: n for n in norm_models}
        ext_map = {e.document_id: e for e in ext_models}

        # Concurrency & Scheduler Inspection
        breaker = scoring_facade.hybrid_matching.evaluator.settings if hasattr(scoring_facade.hybrid_matching.evaluator, "settings") else settings
        cerebras_enabled = bool(getattr(settings, "CEREBRAS_API_KEY", None))
        default_concurrency = getattr(settings, "MAX_CONCURRENT_RESUMES", 3)
        max_concurrent = default_concurrency if cerebras_enabled else 1
        throttle_seconds = getattr(settings, "LLM_BATCH_THROTTLE_SECONDS", 0.25)
        print(f"  Queue Concurrency: max_concurrent={max_concurrent} (Sequential={max_concurrent==1}), throttle_seconds={throttle_seconds}")

        # Measure candidate-by-candidate scoring
        scored_candidates = []
        for doc in resumes:
            t_cand_start = perf_counter()
            r_norm = norm_map.get(doc.id)
            r_ext = ext_map.get(doc.id)

            # Sub-timing: Skills Matching (Deterministic 0-50)
            from app.services.matching_service import RequirementBuilder, EvidenceBuilder
            from app.schemas.matching import RequirementKind

            reqs = RequirementBuilder.build(job, weight_config)
            evidence = EvidenceBuilder.build(r_ext)

            t0 = perf_counter()
            skill_reqs = [r for r in reqs if r.kind in {RequirementKind.SKILL, RequirementKind.REQUIRED_SKILL, RequirementKind.PREFERRED_SKILL}]
            det_skills = [scoring_facade.hybrid_matching.matcher.match(r, r_norm, evidence) for r in skill_reqs]
            t_skills_deterministic = (perf_counter() - t0) * 1000

            # Sub-timing: Responsibilities Matching (Groq AI 0-50) + Scoring Persistence
            t0 = perf_counter()
            _telemetry_before = len(GROQ_TELEMETRY_EVENTS)
            saved = await scoring_facade._score(
                doc, job,
                resume=r_norm,
                extracted=r_ext,
                weight_config=weight_config,
                scores_repo=score_repo,
                weights_repo=weight_repo,
                norm_repo=norm_repo,
                ext_repo=ext_repo,
            )
            t_score_pipeline_and_db = (perf_counter() - t0) * 1000
            _cand_telemetry = GROQ_TELEMETRY_EVENTS[_telemetry_before:]
            _llm_tele = _cand_telemetry[0] if _cand_telemetry else {}

            total_cand_time = (perf_counter() - t_cand_start) * 1000
            scored_candidates.append(saved)
            _llm_duration_ms = _llm_tele.get("llm_duration_ms", 0.0)
            _provider_call_ms = _llm_tele.get("provider_wait_ms", 0.0)
            _token_wait_ms = max(0.0, _llm_duration_ms - _provider_call_ms)
            scoring_sub_timings.append({
                "filename": doc.original_filename,
                "deterministic_skills_ms": t_skills_deterministic,
                "responsibilities_groq_ai_and_db_ms": t_score_pipeline_and_db,
                "total_candidate_ms": total_cand_time,
                "final_score": saved.final_score,
                "skills_score": saved.skills_score,
                "resp_score": saved.component_scores.responsibilities.score if (saved.component_scores and saved.component_scores.responsibilities) else 0.0,
                "recommendation": saved.recommendation.value if hasattr(saved.recommendation, "value") else str(saved.recommendation),
                "llm_provider_selected": _llm_tele.get("provider_selected", "none"),
                "llm_estimated_tokens": _llm_tele.get("estimated_tokens", 0),
                "llm_actual_input_tokens": _llm_tele.get("actual_input_tokens", 0),
                "llm_actual_output_tokens": _llm_tele.get("actual_output_tokens", 0),
                "llm_actual_total_tokens": _llm_tele.get("actual_total_tokens", 0),
                "llm_duration_ms": round(_llm_duration_ms, 2),
                "llm_provider_call_ms": round(_provider_call_ms, 2),
                "llm_token_wait_ms": round(_token_wait_ms, 2),
            })

    total_scoring_batch_ms = (perf_counter() - t_score_stage_start) * 1000
    total_llm_token_wait_ms = sum(s["llm_token_wait_ms"] for s in scoring_sub_timings)
    total_llm_tokens = sum(s["llm_actual_total_tokens"] for s in scoring_sub_timings)
    print(f"  Scoring batch completed in {total_scoring_batch_ms:.2f} ms")
    for s in scoring_sub_timings:
        print(f"    - {s['filename']:<35} | Skills (Det 0-50): {s['deterministic_skills_ms']:6.2f}ms [{s['skills_score']:4.1f}] | Resp + Groq AI + DB: {s['responsibilities_groq_ai_and_db_ms']:7.2f}ms [{s['resp_score']:4.1f}] | Total: {s['total_candidate_ms']:7.2f}ms -> Score: {s['final_score']:5.1f} ({s['recommendation']})")
        print(f"        LLM: provider={s['llm_provider_selected']:<8} tokens(est/actual)={s['llm_estimated_tokens']}/{s['llm_actual_total_tokens']} (in={s['llm_actual_input_tokens']},out={s['llm_actual_output_tokens']}) | call_ms={s['llm_provider_call_ms']:7.2f} | token_wait_ms={s['llm_token_wait_ms']:7.2f}")
    print(f"  TOTAL Groq/Cerebras tokens consumed (5 candidates): {total_llm_tokens}")
    print(f"  TOTAL token-bucket wait time (5 candidates): {total_llm_token_wait_ms:.2f} ms ({total_llm_token_wait_ms/1000:.2f} s)")

    # 8. Benchmark Stage 7: Ranking & Candidate Persistence/Listing
    print("\n[STEP 8] Benchmarking Candidate Ranking & Listing (POST /projects/{id}/rankings)...")
    t_rank_stage_start = perf_counter()

    async with AsyncSessionLocal() as session:
        proj_repo = ProjectRepository(session)
        doc_repo = DocumentRepository(session)
        score_repo = ScoringRepository(session)
        rank_repo = RankingRepository(session)
        ranking_service = RankingService(proj_repo, doc_repo, score_repo, rank_repo)

        t0 = perf_counter()
        scores = await score_repo.get_project_scores(project_id)
        t_get_scores_db = (perf_counter() - t0) * 1000

        # Bulk-fetch documents by id in one round trip instead of one get_document() per score
        # (matches the fix applied to RankingService.compute_project_rankings()).
        t0 = perf_counter()
        docs_by_id = {d.id: d for d in await doc_repo.get_documents_by_ids([sc.document_id for sc in scores])}
        candidates = [(sc, docs_by_id[sc.document_id].created_at) for sc in scores if sc.document_id in docs_by_id]
        t_sequential_doc_lookups_db = (perf_counter() - t0) * 1000

        t0 = perf_counter()
        from app.services.ranking import RankingAlgorithm
        existing = await rank_repo.get_existing_rankings(project_id)
        previous = {r.document_id: r.rank_position for r in existing}
        computed = RankingAlgorithm.compute(candidates, previous)
        t_rank_algo = (perf_counter() - t0) * 1000

        t0 = perf_counter()
        await rank_repo.bulk_upsert_rankings(project_id, computed)
        t_bulk_upsert_db = (perf_counter() - t0) * 1000

    total_ranking_ms = (perf_counter() - t_rank_stage_start) * 1000
    print(f"  Ranking computation completed in {total_ranking_ms:.2f} ms")
    print(f"    - Scores DB Query            : {t_get_scores_db:6.2f} ms")
    print(f"    - Bulk Doc Lookup (DB)       : {t_sequential_doc_lookups_db:6.2f} ms (1 round trip instead of {len(scores)} sequential SELECTs)")
    print(f"    - Ranking In-Memory Algorithm: {t_rank_algo:6.2f} ms")
    print(f"    - Bulk Upsert DB Commit      : {t_bulk_upsert_db:6.2f} ms")

    # 9. Clean up test project
    print("\n[STEP 9] Cleaning up benchmark artifacts...")
    async with AsyncSessionLocal() as session:
        from app.models import ParsedDocumentModel, ExtractedResumeModel, NormalizedResumeModel, CandidateScoreModel, CandidateRankingModel
        await session.execute(CandidateRankingModel.__table__.delete().where(CandidateRankingModel.project_id == project_id))
        await session.execute(CandidateScoreModel.__table__.delete().where(CandidateScoreModel.project_id == project_id))
        for doc_id in [r["document_id"] for r in per_resume_upload_timings]:
            await session.execute(NormalizedResumeModel.__table__.delete().where(NormalizedResumeModel.document_id == doc_id))
            await session.execute(ExtractedResumeModel.__table__.delete().where(ExtractedResumeModel.document_id == doc_id))
            await session.execute(ParsedDocumentModel.__table__.delete().where(ParsedDocumentModel.document_id == doc_id))
        await session.execute(DocumentModel.__table__.delete().where(DocumentModel.project_id == project_id))
        await session.execute(ProjectModel.__table__.delete().where(ProjectModel.id == project_id))
        await session.commit()
    print("  Benchmark test data cleaned up.")

    # 10. Summary Report
    print("\n" + "=" * 80)
    print("SUMMARY OF BENCHMARK TIMINGS & BOTTLENECK ANALYSIS")
    print("=" * 80)

    total_pipeline_time_ms = (
        total_batch_upload_ms
        + total_batch_parse_ms
        + total_batch_extract_ms
        + total_batch_norm_ms
        + total_fe_fetches_ms
        + total_scoring_batch_ms
        + total_ranking_ms
    )

    print(f"\nTOTAL BATCH EXECUTION TIME (5 Resumes): {total_pipeline_time_ms / 1000:.2f} s ({total_pipeline_time_ms:.1f} ms)")
    print("\nStage Breakdown (Total Batch Time):")
    print(f"  1. Batch Upload (5 files)         : {total_batch_upload_ms:9.2f} ms ({total_batch_upload_ms/total_pipeline_time_ms*100:5.1f}%)")
    print(f"  2. Resume Parsing (Affinda / local): {total_batch_parse_ms:9.2f} ms ({total_batch_parse_ms/total_pipeline_time_ms*100:5.1f}%)")
    print(f"  3. Resume Extraction              : {total_batch_extract_ms:9.2f} ms ({total_batch_extract_ms/total_pipeline_time_ms*100:5.1f}%)")
    print(f"  4. Resume Normalization           : {total_batch_norm_ms:9.2f} ms ({total_batch_norm_ms/total_pipeline_time_ms*100:5.1f}%)")
    print(f"  5. Frontend Post-Norm Profiling   : {total_fe_fetches_ms:9.2f} ms ({total_fe_fetches_ms/total_pipeline_time_ms*100:5.1f}%)")
    print(f"  6. Scoring (Skills Det + Groq AI) : {total_scoring_batch_ms:9.2f} ms ({total_scoring_batch_ms/total_pipeline_time_ms*100:5.1f}%)")
    print(f"  7. Ranking & Final Persistence    : {total_ranking_ms:9.2f} ms ({total_ranking_ms/total_pipeline_time_ms*100:5.1f}%)")

    # Output detailed JSON for forensic records
    report = {
        "total_pipeline_time_ms": total_pipeline_time_ms,
        "stages": {
            "batch_upload_ms": total_batch_upload_ms,
            "parsing_ms": total_batch_parse_ms,
            "extraction_ms": total_batch_extract_ms,
            "normalization_ms": total_batch_norm_ms,
            "frontend_fetches_ms": total_fe_fetches_ms,
            "scoring_ms": total_scoring_batch_ms,
            "ranking_ms": total_ranking_ms,
        },
        "per_resume_uploads": per_resume_upload_timings,
        "per_resume_parsing": parsing_timings,
        "per_resume_extraction": extraction_timings,
        "per_resume_normalization": normalization_timings,
        "per_resume_scoring": scoring_sub_timings,
    }
    with open("resume_processing_benchmark_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print("\nDetailed trace written to resume_processing_benchmark_report.json")


if __name__ == "__main__":
    asyncio.run(main())
