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
print('Benchmark script skeleton created') 
