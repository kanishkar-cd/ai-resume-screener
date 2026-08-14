import asyncio
import time
import uuid

from app.db.session import AsyncSessionLocal
from app.repositories.project_repository import ProjectRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.repositories.scoring_repository import ScoringRepository
from app.repositories.ranking_repository import RankingRepository
from app.services.project_service import ProjectService
from app.services.extraction_service import ExtractionService
from app.services.normalization_service import NormalizationService
from app.services.jd_extraction_service import JDExtractionService
from app.services.jd_normalization_service import JDNormalizationService
from app.services.scoring_service import ScoringEngineFacade
from app.services.ranking_service import RankingService
from app.schemas.project import ProjectCreate
from app.schemas.document import DocumentCreate, DocumentType, ProcessingStage, ProcessingStatus
from app.schemas.parsed_document import ParsedDocumentCreate, ParserEngine
from app.schemas.weight_config import WeightConfigCreate

SOFTWARE_ENGINEER_JD = """
JOB DESCRIPTION
Job Title: Software Engineer
EXPERIENCE
Experience: 0-2 years
REQUIRED SKILLS
- JavaScript, Python, C++, SQL, HTML, CSS, REST APIs, Git
- Object-Oriented Programming, Data Structures and Algorithms
PREFERRED SKILLS
- React.js, Node.js, Express.js, MongoDB, PostgreSQL, AWS, Docker
EDUCATION
Bachelor degree in Computer Science or Information Technology
RESPONSIBILITIES
- Develop and maintain software applications and RESTful APIs.
"""

CANDIDATES = [
    ("1_Senior_FullStack.txt", """John Doe - Senior FullStack Engineer
Skills: Python, JavaScript, C++, SQL, HTML, CSS, REST APIs, Git, React, Node.js, AWS, Docker
Experience: 3 years at TechCorp
Education: Bachelor of Science in Computer Science
Projects: Built scalable microservices with Python, Node.js, and Docker on AWS.
"""),
    ("2_Junior_Backend.txt", """Jane Smith - Junior Backend Developer
Skills: Python, SQL, REST APIs, Git, PostgreSQL
Experience: 1 year at DataInc
Education: Bachelor of Engineering in IT
Projects: Developed REST APIs using Python and PostgreSQL.
"""),
    ("3_Frontend_Developer.txt", """Alice Johnson - Frontend Developer
Skills: JavaScript, HTML, CSS, React, Git
Experience: 2 years at WebStudio
Education: Bachelor of Technology in CS
Projects: Built interactive web dashboards with React.js.
"""),
    ("4_DevOps_Engineer.txt", """Bob Williams - DevOps Engineer
Skills: Docker, AWS, CI/CD, Git, Linux, Python, SQL
Experience: 4 years at CloudOps
Education: Bachelor of Science in Electronics
Projects: Automated deployment pipelines with Docker and GitHub Actions on AWS.
"""),
    ("5_CS_Intern.txt", """Charlie Brown - CS Intern
Skills: C++, HTML, CSS, Git
Experience: 6 months internship
Education: Bachelor of Science in Computer Science
Projects: Implemented algorithms and data structures in C++.
"""),
    ("6_Data_Analyst.txt", """David Miller - Data Analyst
Skills: SQL, Python, Excel, Tableau
Experience: 2 years at AnalyticsCorp
Education: Bachelor of Science in Mathematics
Projects: Built SQL queries and data dashboards.
"""),
]

async def main():
    print("=== FRESH END-TO-END SCREENING BENCHMARK (POSTGRESQL & 50+50 MODEL) ===")
    async with AsyncSessionLocal() as session:
        projects_repo = ProjectRepository(session)
        docs_repo = DocumentRepository(session)
        parsed_repo = ParsedDocumentRepository(session)
        ext_repo = ExtractionRepository(session)
        norm_repo = NormalizationRepository(session)
        weight_repo = WeightConfigRepository(session)
        score_repo = ScoringRepository(session)
        rank_repo = RankingRepository(session)

        run_uid = str(uuid.uuid4())[:8]

        # 1. Project Creation
        t0 = time.perf_counter()
        project = await ProjectService(projects_repo).create_project(
            ProjectCreate(title="Bench " + run_uid, target_role="Software Engineer", department="Engineering")
        )
        t_proj_ms = (time.perf_counter() - t0) * 1000

        # 2. JD Upload & Processing
        t_jd = time.perf_counter()
        jd_doc = await docs_repo.create(
            DocumentCreate(
                project_id=project.id,
                document_type=DocumentType.JOB_DESCRIPTION,
                original_filename="jd.txt",
                stored_filename="jd_" + run_uid + ".txt",
                file_path="mock_jd",
                file_size_bytes=len(SOFTWARE_ENGINEER_JD),
                file_hash=str(uuid.uuid4()).replace("-", "") * 2,
                mime_type="text/plain",
                processing_stage=ProcessingStage.INGESTION,
                processing_status=ProcessingStatus.COMPLETED,
            )
        )
        await parsed_repo.upsert(
            ParsedDocumentCreate(
                document_id=jd_doc.id,
                raw_text=SOFTWARE_ENGINEER_JD,
                normalized_text=SOFTWARE_ENGINEER_JD,
                page_count=1,
                word_count=len(SOFTWARE_ENGINEER_JD.split()),
                character_count=len(SOFTWARE_ENGINEER_JD),
                parser_engine=ParserEngine.PYMUPDF,
                parsing_duration_ms=10.0,
            )
        )
        await JDExtractionService(docs_repo, parsed_repo, ext_repo).extract_document(jd_doc.id)
        await JDNormalizationService(docs_repo, ext_repo, norm_repo).normalize_document(jd_doc.id)
        t_jd_ms = (time.perf_counter() - t_jd) * 1000

        await weight_repo.upsert(
            project.id,
            WeightConfigCreate(
                passing_score=30.0,
                min_experience_years=0,
                weights={"skills": 50, "experience": 20, "projects": 15, "education": 10, "certifications": 5, "languages": 0},
                mandatory_skills=[],
                required_degree=None,
                required_certifications=[],
                required_languages=[],
                knockout_rules=[],
            ),
        )

        # 3. Resume Upload
        t_up = time.perf_counter()
        cand_docs = []
        for idx, (filename, text_content) in enumerate(CANDIDATES, 1):
            doc = await docs_repo.create(
                DocumentCreate(
                    project_id=project.id,
                    document_type=DocumentType.RESUME,
                    original_filename=filename,
                    stored_filename=run_uid + "_" + filename,
                    file_path="mock_" + filename,
                    file_size_bytes=len(text_content),
                    file_hash=str(uuid.uuid4()).replace("-", "") * 2,
                    mime_type="text/plain",
                    processing_stage=ProcessingStage.INGESTION,
                    processing_status=ProcessingStatus.COMPLETED,
                )
            )
            cand_docs.append((doc, text_content))
        t_up_ms = (time.perf_counter() - t_up) * 1000

        # 4. Resume Parsing
        t_parse = time.perf_counter()
        for doc, text_content in cand_docs:
            await parsed_repo.upsert(
                ParsedDocumentCreate(
                    document_id=doc.id,
                    raw_text=text_content,
                    normalized_text=text_content,
                    page_count=1,
                    word_count=len(text_content.split()),
                    character_count=len(text_content),
                    parser_engine=ParserEngine.PYMUPDF,
                    parsing_duration_ms=10.0,
                )
            )
        t_parse_ms = (time.perf_counter() - t_parse) * 1000

        # 5. Extraction & Affinda/Fallback
        t_ext = time.perf_counter()
        ext_service = ExtractionService(docs_repo, parsed_repo, ext_repo)
        for doc, _ in cand_docs:
            await ext_service.extract_document_data(doc.id)
        t_ext_ms = (time.perf_counter() - t_ext) * 1000

        # 6. Normalization
        t_norm = time.perf_counter()
        norm_service = NormalizationService(docs_repo, ext_repo, norm_repo)
        for doc, _ in cand_docs:
            await norm_service.normalize_document_data(doc.id)
        t_norm_ms = (time.perf_counter() - t_norm) * 1000

        # 7. Deterministic Skill Matching & LLM Evaluation (50+50 Model)
        t_score = time.perf_counter()
        facade = ScoringEngineFacade(projects_repo, docs_repo, norm_repo, ext_repo, weight_repo, score_repo)
        await facade.score_project(project.id)
        t_score_ms = (time.perf_counter() - t_score) * 1000

        # 8. Candidate Ranking & DB Persistence
        t_rank = time.perf_counter()
        ranking_service = RankingService(projects_repo, docs_repo, score_repo, rank_repo)
        await ranking_service.compute_project_rankings(project.id)
        t_rank_ms = (time.perf_counter() - t_rank) * 1000

        # Print Detailed Metrics
        print(f"1. Project Creation & Setup   : {t_proj_ms:.2f} ms")
        print(f"2. JD Extraction & Normalize  : {t_jd_ms:.2f} ms")
        print(f"3. Resumes Ingestion / Upload : {t_up_ms:.2f} ms")
        print(f"4. Document Text Parsing      : {t_parse_ms:.2f} ms")
        print(f"5. Extraction (Affinda/Local) : {t_ext_ms:.2f} ms")
        print(f"6. Normalization              : {t_norm_ms:.2f} ms")
        print(f"7. 50+50 Scoring & LLM Eval   : {t_score_ms:.2f} ms")
        print(f"8. Candidate Ranking & Persist: {t_rank_ms:.2f} ms")
        print(f"TOTAL PIPELINE RUNTIME        : {t_proj_ms + t_jd_ms + t_up_ms + t_parse_ms + t_ext_ms + t_norm_ms + t_score_ms + t_rank_ms:.2f} ms\n")

        print("=== FINAL BIAS-FREE 50+50 RANKING RESULTS ===")
        rankings = await ranking_service.list_rankings(
            project.id,
            page=1,
            page_size=10,
            recommendation=None,
            min_score=None,
            max_score=None,
            is_knocked_out=None,
            search=None,
            sort_by="rank_position",
            order="asc",
        )
        for r in rankings.items:
            cand_doc = next(d[0] for d in cand_docs if d[0].id == r.document_id)
            print(f"Rank #{r.rank_position}: {cand_doc.original_filename:<25} | Final Score: {r.final_score:>5.2f} / 100 | Recommendation: {r.recommendation}")

if __name__ == "__main__":
    asyncio.run(main())
