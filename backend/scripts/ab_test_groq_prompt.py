"""
A/B experiment: current production Groq system prompt (A) vs a compressed variant (B).

Does NOT modify GroqMatchEvaluator._payload's source. Variant B is applied purely via a
runtime monkeypatch that calls the real _payload() (so requirements/evidence JSON, model,
temperature, max_tokens, response_format are byte-identical to production) and then swaps
only messages[0]["content"] (the system prompt) before the payload is sent to Groq.

Runs the real score_project() pipeline for both variants on the same 5 resumes / same JD,
multiple times each, and reports token/latency/score/verdict comparisons.
"""

import asyncio
import io
import json
import sys
import time
from time import perf_counter
from uuid import uuid4

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import structlog

CAPTURED_EVENTS: list[dict] = []


def _capture(_logger, _method_name, event_dict):
    if event_dict.get("event") in ("resume_llm_routing_telemetry", "final_requirement_verdict"):
        CAPTURED_EVENTS.append(dict(event_dict))
    return event_dict


structlog.configure(
    processors=[_capture, structlog.dev.ConsoleRenderer(colors=False)],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

from fastapi import UploadFile

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models import DocumentModel, DocumentTypeEnum, ProjectModel, WeightConfigModel
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.ranking_repository import RankingRepository
from app.repositories.scoring_repository import ScoringRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.project import ProjectCreate
from app.services.document_service import DocumentService
from app.services.extraction_service import ExtractionService
from app.services.normalization_service import NormalizationService
from app.services.parsing_service import ParsingService
from app.services.scoring_service import ScoringEngineFacade
from app.services.storage_service import StorageService
from app.services.matching_service import GroqMatchEvaluator

SAMPLE_RESUME_FILES = [
    {"filename": "23cs196_Yogeshwar_R_1390.pdf", "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\7b215fd1-406c-4a6d-94ed-5fce8cc1ea86.pdf", "candidate": "Yogeshwar R"},
    {"filename": "Harshini_resume.pdf", "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\a034674d-5ea5-4051-be94-993e2e22bf5d.pdf", "candidate": "Harshini"},
    {"filename": "shri ram resume.pdf", "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\a31dd8a4-e910-4bb0-b2cb-596f3a7b7c5e.pdf", "candidate": "Shri Ram"},
    {"filename": "NAVEENA_N_RESUME.pdf", "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\cf1516cc-c28b-481d-bf5a-3038c0ec20b6.pdf", "candidate": "Naveena N"},
    {"filename": "23EC052- JEGADHEES J(RESUME) (1)_5572.pdf", "path": r"..\storage\projects\0b7a7d52-f56d-4f6b-a7f2-55ed49521e84\resumes\df94d3bf-ea62-48f2-a8ac-98c7c847742f.pdf", "candidate": "Jegadhees J"},
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

PROMPT_B = (
    "Evaluate how well the candidate matches each job requirement using continuous (non-binary) "
    "0.0-1.0 scoring -- most real matches are partial.\n\n"
    "INSTRUCTIONS:\n"
    "1. If a requirement bundles multiple sub-skills or sub-duties, decompose it into atomic "
    "sub-claims and evaluate each one per step 2.\n\n"
    "2. For each atomic sub-claim, classify evidence_level against the candidate evidence: "
    "'direct' (explicit tool/skill/duty match), 'adjacent' (similar tool, same domain pattern, "
    "transferable duty), or 'none' (no evidence). Record each as an object in 'sub_claim_evidence': "
    "{\"claim\": \"...\", \"evidence_level\": \"direct|adjacent|none\", \"note\": \"...\"}.\n\n"
    "3. Set 'coverage_score' 0.0-1.0: 1.0=full direct evidence all sub-claims | 0.7-0.9=most "
    "sub-claims direct, minor gaps | 0.4-0.6=partial (some sub-claims met, or all "
    "adjacent/transferable) | 0.1-0.3=weak/tangential | 0.0=no relevant evidence. Do not default "
    "to 0 or 1 out of uncertainty -- estimate the most likely coverage.\n\n"
    "4. Set 'status': 'MATCHED' (coverage>=0.7), 'PARTIALLY_MATCHED' (0.25-0.69), 'NO_MATCH' (<0.25).\n\n"
    "5. In 'evidence_ids', cite ONLY 'evidence_id' values that exist in 'candidate_evidence' and "
    "directly support your verdict. Never invent IDs. MATCHED/PARTIALLY_MATCHED requires at least "
    "one valid evidence_id.\n\n"
    "OUTPUT FORMAT:\n"
    "Return JSON: {\"verdicts\": [{\"requirement_id\": \"string\", \"status\": "
    "\"MATCHED|PARTIALLY_MATCHED|NO_MATCH\", \"sub_claim_evidence\": [{\"claim\": \"string\", "
    "\"evidence_level\": \"direct|adjacent|none\", \"note\": \"string\"}], \"coverage_score\": 0.0, "
    "\"evidence_ids\": [\"string\"], \"reasoning\": \"1-2 sentence justification citing specific evidence\"}]}"
)

_ORIGINAL_PAYLOAD = GroqMatchEvaluator._payload


def _payload_variant_b(self, requirements, evidence, allowed_evidence=None):
    payload = _ORIGINAL_PAYLOAD(self, requirements, evidence, allowed_evidence)
    payload["messages"][0]["content"] = PROMPT_B
    return payload


class PromptVariant:
    def __init__(self, label: str):
        self.label = label

    def __enter__(self):
        if self.label == "B":
            GroqMatchEvaluator._payload = _payload_variant_b
        else:
            GroqMatchEvaluator._payload = _ORIGINAL_PAYLOAD
        return self

    def __exit__(self, *exc):
        GroqMatchEvaluator._payload = _ORIGINAL_PAYLOAD


async def setup_project() -> tuple:
    project_id = uuid4()
    async with AsyncSessionLocal() as session:
        proj_repo = ProjectRepository(session)
        project = await proj_repo.create(ProjectCreate(
            title=f"ABTest-Prompt-{project_id.hex[:6]}", department_code="SOFTWARE_ENGINEERING",
            hiring_level="EXPERIENCED", target_role="Software Engineer", description="Prompt A/B test",
        ))
        project_id = project.id

    async with AsyncSessionLocal() as session:
        from app.api.v1.endpoints.project_documents import process_job_description
        jd_file = UploadFile(filename="jd.txt", file=io.BytesIO(SAMPLE_JD_TEXT.encode("utf-8")), headers={"content-type": "text/plain"})
        await process_job_description(project_id, jd_file, session)

    doc_ids = []
    async with AsyncSessionLocal() as session:
        storage = StorageService()
        doc_repo = DocumentRepository(session)
        proj_repo = ProjectRepository(session)
        doc_service = DocumentService(doc_repo, proj_repo, storage)
        await doc_service._verify_project(project_id)
        from app.services.document_service import validate_file
        from app.schemas.document import DocumentCreate, DocumentType
        for item in SAMPLE_RESUME_FILES:
            with open(item["path"], "rb") as f:
                content = f.read()
            uf = UploadFile(filename=item["filename"], file=io.BytesIO(content), headers={"content-type": "application/pdf"})
            orig_name, ext = await validate_file(uf)
            stored_name, file_path, size, file_hash = await storage.save_file(uf, project_id, "resumes", ext)
            created = await doc_repo.create(DocumentCreate(
                project_id=project_id, document_type=DocumentType.RESUME, original_filename=orig_name,
                stored_filename=stored_name, file_path=file_path, file_size_bytes=size,
                mime_type="application/pdf", file_hash=file_hash,
            ))
            doc_ids.append(created.id)

    for doc_id in doc_ids:
        async with AsyncSessionLocal() as session:
            doc_repo = DocumentRepository(session)
            parsed_repo = ParsedDocumentRepository(session)
            storage = StorageService()
            parse_service = ParsingService(doc_repo, parsed_repo, storage)
            doc = await parse_service._load_document(doc_id)
            path = storage.resolve_file(doc.file_path)
            from app.schemas.document import ProcessingStatus
            await parse_service._set_status(doc_id, ProcessingStatus.PARSING_PENDING, {}, document=doc, refresh=False)
            from asyncio import to_thread
            from app.services.parsers import parse_document_file
            from app.services.parsers.base import text_metrics
            parsed = await to_thread(parse_document_file, path, doc.mime_type)
            word_count, character_count = text_metrics(parsed.raw_text)
            from app.schemas.parsed_document import ParsedDocumentCreate
            await parsed_repo.upsert(ParsedDocumentCreate(
                document_id=doc_id, raw_text=parsed.raw_text, normalized_text=parsed.raw_text,
                page_count=parsed.page_count, word_count=word_count, character_count=character_count,
                parser_engine=parsed.parser_engine, parsing_duration_ms=0,
            ), commit=False, refresh=False)
            await parse_service._set_status(doc_id, ProcessingStatus.PARSED, {}, refresh=False, document=doc)

            ext_repo = ExtractionRepository(session)
            ext_service = ExtractionService(doc_repo, parsed_repo, ext_repo)
            from app.schemas.document import ProcessingStage
            doc2 = await ext_service._get_document(doc_id)
            parsed_row = await parsed_repo.get_by_document_id(doc_id)
            await doc_repo.update_processing(doc_id, ProcessingStage.EXTRACTION, ProcessingStatus.IN_PROGRESS, document=doc2, refresh=False)
            from app.services.extractors import ResumeExtractor
            deterministic = ResumeExtractor().extract(parsed_row.normalized_text)
            ai_extracted = None
            try:
                ai_extracted = await ext_service.ai_resume_extractor.extract(parsed_row.normalized_text)
            except Exception:
                pass
            from app.services.extractors.resume_merge import merge_resume_extractions
            extracted = merge_resume_extractions(deterministic, ai_extracted)
            from app.schemas.extracted_info import ExtractedResumeCreate
            await ext_repo.create_or_update_resume(ExtractedResumeCreate(document_id=doc_id, **extracted), commit=False, refresh=False)
            await doc_repo.update_processing(doc_id, ProcessingStage.COMPLETED, ProcessingStatus.COMPLETED, document=doc2, refresh=False)

            norm_repo = NormalizationRepository(session)
            norm_service = NormalizationService(doc_repo, ext_repo, norm_repo)
            doc3 = await norm_service._get_document(doc_id)
            extracted_row = await norm_service._get_extracted(doc3)
            await doc_repo.update_processing(doc_id, ProcessingStage.NORMALIZATION, ProcessingStatus.IN_PROGRESS, document=doc3, refresh=False)
            from app.services.normalizers import ResumeNormalizer
            values = ResumeNormalizer().normalize(extracted_row)
            from app.schemas.normalized_info import NormalizedResumeCreate
            await norm_repo.create_or_update_resume(NormalizedResumeCreate(document_id=doc_id, extracted_resume_id=extracted_row.id, **values), commit=False, refresh=False)
            await doc_repo.update_processing(doc_id, ProcessingStage.COMPLETED, ProcessingStatus.COMPLETED, document=doc3, refresh=False)

    return project_id, doc_ids


async def run_variant(project_id, doc_ids, label: str, run_idx: int) -> dict:
    global CAPTURED_EVENTS
    CAPTURED_EVENTS = []
    # GroqMatchEvaluator's response cache keys on (requirements, evidence, model, threshold,
    # allowed_evidence) -- it does NOT include the system prompt text, so without clearing it here
    # every run after the first would silently return variant A's cached verdicts with zero tokens
    # and zero wait, regardless of which prompt variant is active. Each A/B run must be a real call.
    GroqMatchEvaluator._cache.clear()
    with PromptVariant(label):
        t0 = perf_counter()
        # Neon's pooled connections can be dropped server-side while this outer session sits idle
        # during the (possibly long) token-wait inside score_project -- the per-candidate inner
        # sessions do the real work and commit fine regardless. Build `result` before the session
        # closes, and don't let a failed close() on an already-dead connection discard it.
        session = AsyncSessionLocal()
        try:
            facade = ScoringEngineFacade(
                ProjectRepository(session), DocumentRepository(session), NormalizationRepository(session),
                ExtractionRepository(session), ScoringRepository(session), WeightConfigRepository(session),
            )
            result = await facade.score_project(project_id)
        finally:
            try:
                await session.close()
            except Exception as close_exc:
                print(f"  [warn] outer session close failed (stale connection, ignored): {close_exc}")
        wall_ms = (perf_counter() - t0) * 1000.0

    telemetry = [e for e in CAPTURED_EVENTS if e.get("event") == "resume_llm_routing_telemetry"]
    verdicts = [e for e in CAPTURED_EVENTS if e.get("event") == "final_requirement_verdict" and str(e.get("requirement_id", "")).startswith("responsibility")]

    filename_by_doc = {}
    for attempt in range(3):
        try:
            async with AsyncSessionLocal() as session:
                doc_repo = DocumentRepository(session)
                for did in doc_ids:
                    d = await doc_repo.get_document(did)
                    filename_by_doc[did] = d.original_filename if d else str(did)
            break
        except Exception as lookup_exc:
            print(f"  [warn] filename lookup attempt {attempt + 1} failed: {lookup_exc}")
            await asyncio.sleep(1.0)

    candidates = []
    for sc in result.scores:
        candidates.append({
            "filename": filename_by_doc.get(sc.document_id, str(sc.document_id)),
            "final_score": sc.final_score,
            "skills_score": sc.skills_score,
            "resp_score": sc.component_scores.responsibilities.score if (sc.component_scores and sc.component_scores.responsibilities) else 0.0,
            "recommendation": sc.recommendation.value if hasattr(sc.recommendation, "value") else str(sc.recommendation),
        })

    total_in = sum(t.get("actual_input_tokens", 0) for t in telemetry)
    total_out = sum(t.get("actual_output_tokens", 0) for t in telemetry)
    total_tok = sum(t.get("actual_total_tokens", 0) for t in telemetry)
    total_wait = sum(max(0.0, t.get("llm_duration_ms", 0.0) - t.get("provider_wait_ms", 0.0)) for t in telemetry)
    n_calls = len(telemetry)

    status_counts: dict[str, int] = {}
    for v in verdicts:
        st = v.get("final_status", "unknown")
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        "variant": label, "run": run_idx, "wall_clock_ms": wall_ms,
        "input_tokens": total_in, "output_tokens": total_out, "total_tokens": total_tok,
        "token_wait_ms": total_wait, "n_calls": n_calls,
        "candidates": candidates, "status_counts": status_counts,
        "requirement_verdicts": [{"req": v.get("requirement_id"), "status": v.get("final_status"), "method": v.get("method")} for v in verdicts],
    }


async def cleanup(project_id, doc_ids):
    async with AsyncSessionLocal() as session:
        from app.models import ParsedDocumentModel, ExtractedResumeModel, NormalizedResumeModel, CandidateScoreModel, CandidateRankingModel
        await session.execute(CandidateRankingModel.__table__.delete().where(CandidateRankingModel.project_id == project_id))
        await session.execute(CandidateScoreModel.__table__.delete().where(CandidateScoreModel.project_id == project_id))
        for doc_id in doc_ids:
            await session.execute(NormalizedResumeModel.__table__.delete().where(NormalizedResumeModel.document_id == doc_id))
            await session.execute(ExtractedResumeModel.__table__.delete().where(ExtractedResumeModel.document_id == doc_id))
            await session.execute(ParsedDocumentModel.__table__.delete().where(ParsedDocumentModel.document_id == doc_id))
        await session.execute(DocumentModel.__table__.delete().where(DocumentModel.project_id == project_id))
        await session.execute(ProjectModel.__table__.delete().where(ProjectModel.id == project_id))
        await session.commit()


async def main():
    print("=" * 80)
    print("GROQ SYSTEM PROMPT A/B EXPERIMENT")
    print("=" * 80)
    print("Setting up project + resumes (parse/extract/normalize, once)...")
    project_id, doc_ids = await setup_project()
    print(f"Project ready: {project_id}")

    NUM_RUNS = 2
    all_results = []
    try:
        for label in ["A", "B"]:
            for run_idx in range(1, NUM_RUNS + 1):
                print(f"\n--- Running variant {label}, run {run_idx}/{NUM_RUNS} ---")
                res = None
                for attempt in range(2):
                    try:
                        res = await run_variant(project_id, doc_ids, label, run_idx)
                        break
                    except Exception as run_exc:
                        print(f"  [warn] run failed (attempt {attempt + 1}/2): {type(run_exc).__name__}: {run_exc}")
                        await asyncio.sleep(2.0)
                if res is None:
                    print(f"  [error] variant {label} run {run_idx} failed twice, skipping")
                    continue
                all_results.append(res)
                print(f"  wall_clock={res['wall_clock_ms']/1000:.2f}s  tokens(in/out/total)={res['input_tokens']}/{res['output_tokens']}/{res['total_tokens']}  wait={res['token_wait_ms']/1000:.2f}s  calls={res['n_calls']}")
                for c in res["candidates"]:
                    print(f"    {c['filename']:<40} final={c['final_score']:5.1f} resp={c['resp_score']:5.1f} -> {c['recommendation']}")
                print(f"  status_counts={res['status_counts']}")
                with open("ab_prompt_test_report.json", "w", encoding="utf-8") as f:
                    json.dump(all_results, f, indent=2, default=str)
    finally:
        print("\nCleaning up...")
        try:
            await cleanup(project_id, doc_ids)
        except Exception as cleanup_exc:
            print(f"  [warn] cleanup failed: {cleanup_exc}")

    with open("ab_prompt_test_report.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str)
    print("\nWrote ab_prompt_test_report.json")


if __name__ == "__main__":
    asyncio.run(main())
