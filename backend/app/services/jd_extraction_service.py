"""
JD Extraction Service
=====================
Regex + heuristic extraction of structured requirements from raw parsed text.
No external AI/LLM dependency — deterministic, fast, and offline-capable.
"""
from __future__ import annotations

import re
from collections import Counter
from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, ConflictException, InternalServerException
from app.models.document import DocumentTypeEnum, ProcessingStatusEnum
from app.repositories.document_repository import DocumentRepository
from app.repositories.extracted_jd_repository import ExtractedJDRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.schemas.document import DocumentType, ProcessingStage, ProcessingStatus
from app.schemas.extracted_jd import ExtractedJDCreate, ExtractedJDRead, JDExtractResult
from app.services.document_service import DocumentNotFoundException

logger = structlog.get_logger(__name__)

# ─── Curated Vocabulary ─────────────────────────────────────────────────────

SKILLS_VOCABULARY: frozenset[str] = frozenset({
    # Languages
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++",
    "c#", "ruby", "php", "swift", "kotlin", "scala", "r", "matlab", "perl",
    "bash", "shell", "powershell",
    # Web / Frontend
    "react", "react.js", "reactjs", "vue", "vue.js", "vuejs", "angular", "angularjs",
    "svelte", "nextjs", "next.js", "nuxtjs", "html", "css", "sass", "less",
    "tailwind", "tailwindcss", "bootstrap", "jquery", "webpack", "vite",
    # Backend / API
    "fastapi", "django", "flask", "express", "express.js", "spring", "spring boot",
    "laravel", "rails", "ruby on rails", "asp.net", "node.js", "nodejs",
    "graphql", "rest", "restful", "grpc", "websocket", "oauth", "jwt",
    # Data / ML
    "tensorflow", "pytorch", "keras", "scikit-learn", "sklearn", "pandas",
    "numpy", "spark", "hadoop", "kafka", "airflow", "mlflow", "huggingface",
    "langchain", "openai", "llm", "nlp", "computer vision", "deep learning",
    "machine learning", "data science", "data engineering",
    # Databases
    "postgresql", "mysql", "sqlite", "mongodb", "redis", "elasticsearch",
    "cassandra", "dynamodb", "bigquery", "snowflake", "oracle", "sql server",
    "mariadb", "neo4j", "influxdb",
    # Cloud / Infra
    "aws", "azure", "gcp", "google cloud", "heroku", "vercel", "netlify",
    "docker", "kubernetes", "k8s", "helm", "terraform", "ansible", "jenkins",
    "gitlab", "github actions", "ci/cd", "devops", "sre",
    # Tools
    "git", "jira", "confluence", "slack", "figma", "postman", "swagger",
    "linux", "unix", "nginx", "apache", "rabbitmq", "celery",
    # Methodologies
    "agile", "scrum", "kanban", "tdd", "bdd", "microservices", "serverless",
    "solid", "clean architecture", "ddd", "event-driven",
})

CERTIFICATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\baws\s+(?:certified|solutions\s+architect|developer|sysops|devops)\b",
        r"\bazure\s+(?:certified|fundamentals|associate|expert)\b",
        r"\bgcp\s+(?:certified|associate|professional)\b",
        r"\bcka\b",              # Certified Kubernetes Administrator
        r"\bckad\b",             # Certified Kubernetes Application Developer
        r"\bpmp\b",              # Project Management Professional
        r"\bcissp\b",            # Certified Information Systems Security Professional
        r"\bccna\b",             # Cisco Certified Network Associate
        r"\bcompTIA\s+\w+\b",
        r"\bscrum\s+master\b",
        r"\bcsm\b",              # Certified Scrum Master
        r"\bocjp\b",             # Oracle Certified Java Programmer
        r"\btensorflow\s+developer\b",
        r"\bprofessional\s+(?:cloud|data|ml)\s+(?:architect|engineer|scientist)\b",
    ]
]

DEGREE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(?:bachelor(?:'?s)?|b\.?\s*(?:sc|e|tech|s)|undergraduate)\s*(?:degree|of|in)?\s*(?:computer\s*science|software|engineering|it|information\s*technology|mathematics|statistics|physics|electrical|mechanical)?\b",
        r"\b(?:master(?:'?s)?|m\.?\s*(?:sc|e|tech|s|ba)|postgraduate|graduate)\s*(?:degree|of|in)?\s*(?:computer\s*science|software|engineering|data\s*science|machine\s*learning|it|information\s*technology|mathematics)?\b",
        r"\b(?:phd|ph\.d|doctorate|doctoral)\b",
        r"\b(?:mba|master\s+of\s+business\s+administration)\b",
        r"\b(?:associate\s+degree)\b",
    ]
]

EXPERIENCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(\d+)\+\s*years?\s+(?:of\s+)?(?:relevant\s+)?(?:professional\s+)?experience\b",
        r"\bminimum\s+(?:of\s+)?(\d+)\s+years?\b",
        r"\b(\d+)\s*[-–]\s*(\d+)\s+years?\s+(?:of\s+)?experience\b",
        r"\bat\s+least\s+(\d+)\s+years?\b",
        r"\b(\d+)\s+years?\s+(?:of\s+)?(?:strong\s+)?(?:hands[-\s]on\s+)?experience\b",
        r"\b(\d+)\s+to\s+(\d+)\s+years?\b",
    ]
]

RESPONSIBILITY_VERBS: frozenset[str] = frozenset({
    "design", "develop", "build", "implement", "create", "architect", "lead",
    "manage", "coordinate", "collaborate", "maintain", "optimize", "improve",
    "deploy", "monitor", "integrate", "test", "review", "write", "own",
    "deliver", "drive", "ensure", "establish", "define", "evaluate",
    "analyze", "research", "document", "support", "troubleshoot", "mentor",
})

DOMAIN_SIGNALS: dict[str, list[str]] = {
    "Software Engineering": [
        "software engineer", "backend", "frontend", "full stack", "web development",
        "api", "microservices", "software development",
    ],
    "Data Science": [
        "data scientist", "data science", "machine learning", "statistical modeling",
        "predictive analytics", "data analysis", "feature engineering",
    ],
    "Data Engineering": [
        "data engineer", "data pipeline", "etl", "airflow", "spark", "hadoop",
        "data warehouse", "dbt",
    ],
    "DevOps / Infrastructure": [
        "devops", "site reliability", "sre", "infrastructure", "kubernetes",
        "terraform", "ci/cd", "deployment", "cloud operations",
    ],
    "Machine Learning / AI": [
        "machine learning engineer", "ml engineer", "deep learning", "llm",
        "ai engineer", "computer vision", "nlp", "transformer",
    ],
    "Mobile Development": [
        "mobile developer", "ios", "android", "flutter", "react native",
        "swift", "kotlin", "mobile app",
    ],
    "Security": [
        "security engineer", "cybersecurity", "cissp", "penetration testing",
        "soc", "compliance", "infosec",
    ],
    "Product / Management": [
        "product manager", "project manager", "pmp", "roadmap", "stakeholder",
        "agile coach", "scrum master",
    ],
}

STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "this", "that", "these", "those", "it", "its", "we", "you", "they",
    "their", "our", "your", "who", "what", "which", "when", "where", "how",
    "if", "then", "than", "so", "not", "no", "nor", "yet", "both", "either",
    "each", "any", "all", "most", "more", "such", "up", "about", "into",
    "through", "during", "including", "using", "experience", "strong",
    "excellent", "good", "role", "position", "job", "work", "working",
    "team", "candidate", "must", "required", "requirements", "preferred",
    "knowledge", "ability", "skills", "understanding",
})

BULLET_PATTERN = re.compile(r"^[\s]*[-•*►▸▶·‣⁃◆○●✦✧★☆✱*]+\s+", re.MULTILINE)
NUMBERED_PATTERN = re.compile(r"^[\s]*\d+[.)]\s+", re.MULTILINE)


# ─── Extractor Logic ────────────────────────────────────────────────────────

def _extract_skills(text: str) -> tuple[list[str], float]:
    """Match skill terms against curated vocabulary."""
    text_lower = text.lower()
    found: list[str] = []
    for skill in sorted(SKILLS_VOCABULARY):
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, text_lower):
            found.append(skill)
    confidence = min(1.0, len(found) / 10) if found else 0.0
    return sorted(set(found)), round(confidence, 2)


def _extract_responsibilities(text: str) -> tuple[list[str], float]:
    """Extract bullet-point / numbered list items that start with action verbs."""
    lines: list[str] = []

    # Strip bullet markers and collect lines
    for line in text.splitlines():
        cleaned = BULLET_PATTERN.sub("", line)
        cleaned = NUMBERED_PATTERN.sub("", cleaned).strip()
        if cleaned:
            lines.append(cleaned)

    responsibilities: list[str] = []
    for line in lines:
        first_word = line.split()[0].lower().rstrip(".,;:") if line.split() else ""
        if first_word in RESPONSIBILITY_VERBS and len(line) > 20:
            responsibilities.append(line)

    confidence = min(1.0, len(responsibilities) / 5) if responsibilities else 0.0
    return responsibilities[:30], round(confidence, 2)


def _extract_education(text: str) -> tuple[list[str], float]:
    """Find degree and education requirements using regex patterns."""
    found: set[str] = set()
    for pattern in DEGREE_PATTERNS:
        for match in pattern.finditer(text):
            phrase = match.group(0).strip()
            # Normalise whitespace
            phrase = re.sub(r"\s+", " ", phrase)
            if len(phrase) > 3:
                found.add(phrase)
    confidence = min(1.0, len(found) / 2) if found else 0.0
    return sorted(found), round(confidence, 2)


def _extract_experience(text: str) -> tuple[list[str], float]:
    """Extract experience requirement phrases using regex patterns."""
    found: list[str] = []
    for pattern in EXPERIENCE_PATTERNS:
        for match in pattern.finditer(text):
            phrase = match.group(0).strip()
            phrase = re.sub(r"\s+", " ", phrase)
            if phrase not in found:
                found.append(phrase)
    confidence = min(1.0, len(found) / 2) if found else 0.0
    return found[:10], round(confidence, 2)


def _extract_certifications(text: str) -> tuple[list[str], float]:
    """Extract known certification mentions."""
    found: set[str] = set()
    for pattern in CERTIFICATION_PATTERNS:
        for match in pattern.finditer(text):
            phrase = re.sub(r"\s+", " ", match.group(0).strip())
            found.add(phrase)
    confidence = min(1.0, len(found) / 3) if found else 0.0
    return sorted(found), round(confidence, 2)


def _extract_keywords(text: str, top_n: int = 30) -> list[str]:
    """Extract high-frequency content words as domain keywords."""
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_+#.-]{2,}\b", text.lower())
    filtered = [w for w in words if w not in STOP_WORDS and not w.isdigit()]
    counter = Counter(filtered)
    return [word for word, _ in counter.most_common(top_n)]


def _classify_domain(text: str) -> str | None:
    """Return the best-matching domain label based on keyword signals."""
    text_lower = text.lower()
    scores: dict[str, int] = {domain: 0 for domain in DOMAIN_SIGNALS}
    for domain, signals in DOMAIN_SIGNALS.items():
        for signal in signals:
            if signal in text_lower:
                scores[domain] += 1
    best_domain = max(scores, key=lambda d: scores[d])
    return best_domain if scores[best_domain] > 0 else None


# ─── Exceptions ─────────────────────────────────────────────────────────────

class DocumentNotExtractableException(ConflictException):
    error_code = "DOCUMENT_NOT_EXTRACTABLE"
    default_message = "Document must be in PARSED or COMPLETED status to extract."


class ExtractedJDNotFoundException(AppException):
    status_code = 404
    error_code = "EXTRACTED_JD_NOT_FOUND"
    default_message = "No extraction result was found for this document."


# ─── Service ────────────────────────────────────────────────────────────────

class JDExtractionService:
    """Extract structured fields from a parsed JD document."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        parsed_repository: ParsedDocumentRepository,
        extracted_repository: ExtractedJDRepository,
    ) -> None:
        self.document_repository = document_repository
        self.parsed_repository = parsed_repository
        self.extracted_repository = extracted_repository

    async def extract_document(self, document_id: UUID) -> JDExtractResult:
        document = await self._load_document(document_id)

        # Only JD documents are handled here
        if document.document_type != DocumentTypeEnum.JOB_DESCRIPTION:
            raise DocumentNotExtractableException(
                "Extraction endpoint supports JOB_DESCRIPTION documents only."
            )

        current_status = ProcessingStatusEnum(document.processing_status.value)
        extractable = {
            ProcessingStatusEnum.PARSED,
            ProcessingStatusEnum.COMPLETED,
            ProcessingStatusEnum.FAILED,
        }
        if current_status not in extractable:
            raise DocumentNotExtractableException()

        # Load parsed text
        try:
            parsed = await self.parsed_repository.get_by_document_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve parsed document.") from exc

        if parsed is None or not parsed.raw_text:
            raise DocumentNotExtractableException(
                "Document must be parsed before extraction."
            )

        raw_text = parsed.raw_text

        # Mark IN_PROGRESS
        metadata = dict(document.metadata_json or {})
        await self._set_status(
            document_id,
            ProcessingStatus.IN_PROGRESS,
            {**metadata, "extraction_error": None},
        )

        try:
            skills, skills_conf = _extract_skills(raw_text)
            responsibilities, resp_conf = _extract_responsibilities(raw_text)
            education, edu_conf = _extract_education(raw_text)
            experience, exp_conf = _extract_experience(raw_text)
            certifications, cert_conf = _extract_certifications(raw_text)
            keywords = _extract_keywords(raw_text)
            domain = _classify_domain(raw_text)

            confidence_scores = {
                "skills": skills_conf,
                "responsibilities": resp_conf,
                "education": edu_conf,
                "experience": exp_conf,
                "certifications": cert_conf,
                "overall": round(
                    (skills_conf + resp_conf + edu_conf + exp_conf + cert_conf) / 5, 2
                ),
            }

            payload = ExtractedJDCreate(
                document_id=document_id,
                domain=domain,
                skills=skills,
                responsibilities=responsibilities,
                education=education,
                experience=experience,
                certifications=certifications,
                keywords=keywords,
                confidence_scores=confidence_scores,
                raw_metadata={"source_word_count": parsed.word_count},
            )

            try:
                await self.extracted_repository.upsert(payload)
            except SQLAlchemyError as exc:
                raise InternalServerException("Unable to persist extraction result.") from exc

            updated = await self._set_status(
                document_id,
                ProcessingStatus.COMPLETED,
                {**metadata, "extraction_error": None, "extraction_stage": "EXTRACTION"},
            )
        except AppException:
            await self._set_status(
                document_id,
                ProcessingStatus.FAILED,
                {**metadata, "extraction_error": "Extraction failed."},
            )
            raise
        except Exception as exc:
            await self._set_status(
                document_id,
                ProcessingStatus.FAILED,
                {**metadata, "extraction_error": str(exc)},
            )
            logger.exception(
                "jd_extraction_failed",
                document_id=str(document_id),
                error=str(exc),
            )
            raise InternalServerException("JD extraction failed.") from exc

        logger.info(
            "jd_extracted_successfully",
            document_id=str(document_id),
            skills_count=len(skills),
            domain=domain,
        )
        return JDExtractResult(
            document_id=document_id,
            document_type=DocumentType.JOB_DESCRIPTION,
            processing_stage=ProcessingStage.EXTRACTION,
            processing_status=ProcessingStatus.COMPLETED,
            message=f"Extracted {len(skills)} skills, {len(responsibilities)} responsibilities, domain={domain!r}.",
        )

    async def get_extracted_document(self, document_id: UUID) -> ExtractedJDRead:
        await self._load_document(document_id)
        try:
            extracted = await self.extracted_repository.get_by_document_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve extraction result.") from exc
        if extracted is None:
            raise ExtractedJDNotFoundException()
        return ExtractedJDRead.model_validate(extracted)

    async def _load_document(self, document_id: UUID):
        try:
            document = await self.document_repository.get_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None:
            raise DocumentNotFoundException()
        return document

    async def _set_status(
        self,
        document_id: UUID,
        status: ProcessingStatus,
        metadata: dict,
        *,
        commit: bool = True,
    ):
        try:
            updated = await self.document_repository.update_status(
                document_id, status, metadata, commit=commit
            )
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to update document status.") from exc
        if updated is None:
            raise DocumentNotFoundException()
        return updated
