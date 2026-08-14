import asyncio, time  
from uuid import uuid4  
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
from app.services.document_service import DocumentService  
from app.services.parsing_service import ParsingService  
from app.services.extraction_service import ExtractionService  
from app.services.normalization_service import NormalizationService  
from app.services.jd_extraction_service import JDExtractionService  
from app.services.jd_normalization_service import JDNormalizationService  
from app.services.scoring_service import ScoringEngineFacade  
from app.services.ranking_service import RankingService  
from app.schemas.project import ProjectCreate  
from app.schemas.document import DocumentCreate, DocumentType, ProcessingStage, ProcessingStatus  
SOFTWARE_ENGINEER_JD = '''JOB DESCRIPTION\nJob Title: Software Engineer\nEXPERIENCE\nExperience: 0-2 years\nREQUIRED SKILLS\n- JavaScript, Python, C++, SQL, HTML, CSS, REST APIs, Git\n- Object-Oriented Programming, Data Structures and Algorithms\nPREFERRED SKILLS\n- React.js, Node.js, Express.js, MongoDB, PostgreSQL, AWS, Docker\nEDUCATION\nBachelor degree in Computer Science or Information Technology\nRESPONSIBILITIES\n- Develop and maintain software applications and RESTful APIs.\n'''  
RESUMES = [  
  ('cand1_senior.txt', 'John Doe - Senior Engineer\nSkills: Python, JavaScript, C++, SQL, HTML, CSS, REST APIs, Git, React, Node.js, AWS, Docker\nExperience: 3 years at TechCorp\nEducation: Bachelor of Science in Computer Science\nProjects: Built microservices with Python and Docker on AWS.'),  
  ('cand2_backend.txt', 'Jane Smith - Junior Backend Developer\nSkills: Python, SQL, REST APIs, Git, PostgreSQL\nExperience: 1 year at DataInc\nEducation: Bachelor of Engineering in IT\nProjects: Developed REST API using Python.'),  
  ('cand3_frontend.txt', 'Alice Johnson - Frontend Developer\nSkills: JavaScript, HTML, CSS, React, Git\nExperience: 2 years at WebStudio\nEducation: Bachelor of Technology in CS\nProjects: Built UI dashboards with React.js.'),  
  ('cand4_devops.txt', 'Bob Williams - DevOps Engineer\nSkills: Docker, AWS, CI/CD, Git, Linux, Python, SQL\nExperience: 4 years at CloudOps\nEducation: Bachelor of Science in Electronics\nProjects: Automated deployment pipelines with Docker on AWS.'),  
  ('cand5_intern.txt', 'Charlie Brown - Intern\nSkills: C++, HTML, CSS, Git\nExperience: 6 months internship\nEducation: Bachelor of Science in CS\nProjects: Implemented basic data structures in C++.')  
]  
async def main():  
  print('Starting PostgreSQL pipeline benchmark for 5 candidate resumes...')  
  async with AsyncSessionLocal() as session:  
    projects_repo = ProjectRepository(session)  
    docs_repo = DocumentRepository(session)  
    parsed_repo = ParsedDocumentRepository(session)  
    ext_repo = ExtractionRepository(session)  
    norm_repo = NormalizationRepository(session)  
    weight_repo = WeightConfigRepository(session)  
    score_repo = ScoringRepository(session)  
    rank_repo = RankingRepository(session)  
    t0 = time.perf_counter()  
    project = await ProjectService(projects_repo).create_project(ProjectCreate(title='Bench Project', target_role='Software Engineer', department='Engineering'))  
    print('Stage 1 - Project Creation:', round((time.perf_counter() - t0)*1000, 2), 'ms')  
    t_jd = time.perf_counter()  
    jd_doc = await docs_repo.create(DocumentCreate(project_id=project.id, document_type=DocumentType.JOB_DESCRIPTION, original_filename='jd.txt', file_path='mock_jd', file_size_bytes=len(SOFTWARE_ENGINEER_JD), file_hash=str(uuid4()), mime_type='text/plain', processing_stage=ProcessingStage.INGESTION, processing_status=ProcessingStatus.COMPLETED))  
    await parsed_repo.create_or_update(jd_doc.id, SOFTWARE_ENGINEER_JD, len(SOFTWARE_ENGINEER_JD.split()))  
    await JDExtractionService(docs_repo, parsed_repo, ext_repo).extract_document(jd_doc.id)  
    await JDNormalizationService(docs_repo, ext_repo, norm_repo).normalize_document(jd_doc.id)  
    print('Stage 2 - JD Processing:', round((time.perf_counter() - t_jd)*1000, 2), 'ms')  
    await weight_repo.create(project.id, passing_score=30.0, min_experience_years=0, weights={'skills': 50, 'experience': 20, 'projects': 15, 'education': 10, 'certifications': 5, 'languages': 0})  
    cand_docs = []  
    t_up = time.perf_counter()  
    for filename, text_content in RESUMES:  
      doc = await docs_repo.create(DocumentCreate(project_id=project.id, document_type=DocumentType.RESUME, original_filename=filename, file_path='mock_' + filename, file_size_bytes=len(text_content), file_hash=str(uuid4()), mime_type='text/plain', processing_stage=ProcessingStage.INGESTION, processing_status=ProcessingStatus.COMPLETED))  
      cand_docs.append((doc, text_content))  
    print('Stage 3a - 5 Resumes Upload:', round((time.perf_counter() - t_up)*1000, 2), 'ms')  
    t_parse = time.perf_counter()  
    for doc, text_content in cand_docs:  
      await parsed_repo.create_or_update(doc.id, text_content, len(text_content.split()))  
    print('Stage 3b - 5 Resumes Parsing:', round((time.perf_counter() - t_parse)*1000, 2), 'ms')  
    t_ext = time.perf_counter()  
    ext_service = ExtractionService(docs_repo, parsed_repo, ext_repo)  
    for doc, _ in cand_docs:  
      await ext_service.extract_document_data(doc.id)  
    print('Stage 3c - 5 Resumes Extraction:', round((time.perf_counter() - t_ext)*1000, 2), 'ms')  
    t_norm = time.perf_counter()  
    norm_service = NormalizationService(docs_repo, ext_repo, norm_repo)  
    for doc, _ in cand_docs:  
      await norm_service.normalize_document(doc.id)  
    print('Stage 4 - 5 Resumes Normalization:', round((time.perf_counter() - t_norm)*1000, 2), 'ms')  
    t_score = time.perf_counter()  
    facade = ScoringEngineFacade(projects_repo, docs_repo, norm_repo, ext_repo, weight_repo, score_repo)  
    await facade.score_project(project.id)  
    print('Stage 5 - 5 Resumes 50+50 Model Scoring:', round((time.perf_counter() - t_score)*1000, 2), 'ms')  
    t_rank = time.perf_counter()  
    ranking_service = RankingService(projects_repo, docs_repo, score_repo, rank_repo)  
    await ranking_service.compute_project_rankings(project.id)  
    print('Stage 6 - 5 Resumes Candidate Ranking:', round((time.perf_counter() - t_rank)*1000, 2), 'ms')  
    print('--- BENCHMARK RESULTS ---')  
    rankings_list = await ranking_service.list_rankings(project.id, page=1, page_size=10, recommendation=None, min_score=None, max_score=None, is_knocked_out=None, search=None, sort_by='rank', order='asc')  
    for item in rankings_list.items:  
      cand_doc = next(d[0] for d in cand_docs if d[0].id == item.document_id)  
      print(cand_doc.original_filename, round(item.final_score, 2), item.recommendation)  
if __name__ == '__main__':  
  asyncio.run(main())  
