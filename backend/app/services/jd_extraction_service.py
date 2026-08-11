"""
JD Extraction Service
=====================
Regex + heuristic extraction of structured requirements from raw parsed text.
No external AI/LLM dependency — deterministic, fast, and offline-capable.
"""
from __future__ import annotations

import re
from collections import Counter
from time import perf_counter
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
from app.services.extractors.ai_jd_extractor import AIJDExtractor

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
    "rest api", "rest apis", "object-oriented programming",
    "data structures and algorithms", "software development and debugging",
    "iot", "embedded systems", "plc programming",
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
        r"\b(\d+)\s*[-–—]\s*(\d+)\s+years?(?:\s+(?:of\s+)?(?:professional\s+or\s+internship\s+)?experience)?\b",
        r"\bat\s+least\s+(\d+)\s+years?\b",
        r"\b(\d+)\s+years?\s+(?:of\s+)?(?:strong\s+)?(?:hands[-\s]on\s+)?experience\b",
        r"\b(\d+)\s+to\s+(\d+)\s+years?\b",
    ]
]

RESPONSIBILITY_VERBS: frozenset[str] = frozenset({
    "design", "develop", "build", "implement", "create", "architect", "lead",
    "manage", "coordinate", "collaborate", "maintain", "optimize", "improve",
    "deploy", "monitor", "integrate", "test", "review", "write", "own",
    "deliver", "drive", "ensure", "establish", "define", "evaluate", "work",
    "use", "contribute",
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

SECTION_HEADINGS = {
    "job description": "description",
    "key responsibilities": "responsibilities", "responsibilities": "responsibilities",
    "required skills": "required_skills", "technical skills": "required_skills",
    "required qualifications": "required_skills",
    "preferred skills": "preferred_skills", "nice to have": "preferred_skills",
    "preferred qualifications": "preferred_skills",
    "education": "education", "education requirements": "education",
    "qualifications": "education",
    "experience": "experience", "experience required": "experience",
    "keywords": "keywords",
}

SKILL_CANONICAL = {
    "JavaScript": ("javascript",), "Python": ("python",), "C++": ("c++",),
    "SQL": ("sql",), "HTML": ("html",), "CSS": ("css",),
    "REST APIs": ("rest api", "rest apis", "restful api", "restful apis", "restful"),
    "Git": ("git",), "Object-Oriented Programming": ("object-oriented programming", "object oriented programming", "oop"),
    "Data Structures and Algorithms": ("data structures and algorithms", "data structures & algorithms", "dsa"),
    "Software development and debugging": ("software development and debugging", "software development", "debugging"),
    "React.js": ("react.js", "reactjs", "react"), "Node.js": ("node.js", "nodejs"),
    "Express.js": ("express.js", "expressjs", "express"), "MongoDB": ("mongodb",),
    "PostgreSQL": ("postgresql", "postgres"), "AWS": ("aws",), "Docker": ("docker",),
    "CI/CD": ("ci/cd", "continuous integration and continuous delivery", "continuous integration/continuous delivery"),
    "Jenkins": ("jenkins",), "GitHub Actions": ("github actions",), "IoT": ("iot",),
    "Embedded Systems": ("embedded systems", "embedded system"), "PLC Programming": ("plc programming",),
    "Machine Learning": ("machine learning",), "Linux": ("linux",),
}

DISCIPLINE_CANONICAL = {
    "Computer Science": ("computer science",), "Information Technology": ("information technology",),
    "Electronics & Instrumentation": ("electronics & instrumentation", "electronics and instrumentation"),
    "Artificial Intelligence & Data Science": ("artificial intelligence & data science", "artificial intelligence and data science"),
    "Electronics": ("electronics",), "Related Engineering": ("related engineering", "related engineering discipline"),
}


def _split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        prefix, separator, remainder = line.partition(":")
        candidate = re.sub(r"\s+", " ", prefix if separator else line).strip().casefold()
        heading = SECTION_HEADINGS.get(candidate) if len(candidate) <= 60 else None
        if heading:
            current = heading
            sections.setdefault(current, [])
            if separator and remainder.strip():
                sections[current].append(remainder.strip())
        else:
            sections.setdefault(current, []).append(line)
    return {key: "\n".join(lines) for key, lines in sections.items()}


def _canonical_skills(text: str) -> list[str]:
    lowered = text.casefold()
    found: list[str] = []
    for canonical, aliases in SKILL_CANONICAL.items():
        if any(re.search(r"(?<![\w])" + re.escape(alias) + r"(?![\w])", lowered) for alias in aliases):
            found.append(canonical)
    return found


def _extract_job_title(text: str, sections: dict[str, str]) -> str | None:
    match = re.search(r"(?im)^\s*(?:job\s*title|position|role)\s*:\s*([^\n]{2,80})$", text)
    if match:
        return match.group(1).strip()
    for line in sections.get("header", "").splitlines()[:5]:
        if re.fullmatch(r"(?:senior\s+|junior\s+|lead\s+)?(?:software|devops|data|machine learning|frontend|backend|full stack)\s+(?:engineer|developer|scientist)", line.strip(), re.I):
            return line.strip()
    return None


def _extract_disciplines(text: str) -> list[str]:
    lowered = text.casefold()
    result: list[str] = []
    for canonical, aliases in DISCIPLINE_CANONICAL.items():
        if any(alias in lowered for alias in aliases):
            result.append(canonical)
    return result


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
        ai_extractor: AIJDExtractor | None = None,
        affinda_service=None,
        storage=None,
    ) -> None:
        self.document_repository = document_repository
        self.parsed_repository = parsed_repository
        self.extracted_repository = extracted_repository
        self.ai_extractor = ai_extractor or AIJDExtractor()
        from app.services.affinda_service import AffindaService
        from app.services.storage_service import StorageService
        self.affinda_service = affinda_service or AffindaService()
        self.storage = storage or StorageService()

    async def extract_document(self, document_id: UUID) -> JDExtractResult:
        started_at = perf_counter()
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
            # Extraction uses an idempotent upsert. Permit recovery when a prior
            # attempt was interrupted after setting IN_PROGRESS (for example,
            # by a transient database/schema failure).
            ProcessingStatusEnum.IN_PROGRESS,
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
            document=document,
            refresh=False,
        )

        affinda_result = await self._try_affinda(document, metadata)
        if affinda_result is not None:
            return affinda_result

        try:
            sections = _split_sections(raw_text)
            skills, skills_conf = _extract_skills(raw_text)
            required_skills = _canonical_skills(sections.get("required_skills", ""))
            preferred_skills = _canonical_skills(sections.get("preferred_skills", ""))
            combined_skill_keys = {value.casefold() for value in skills}
            for value in [*required_skills, *preferred_skills]:
                if value.casefold() not in combined_skill_keys:
                    skills.append(value)
                    combined_skill_keys.add(value.casefold())
            responsibility_source = sections.get("responsibilities", "") or raw_text
            responsibilities, resp_conf = _extract_responsibilities(responsibility_source)
            education_source = sections.get("education", "") or raw_text
            education, edu_conf = _extract_education(education_source)
            education_disciplines = _extract_disciplines(education_source)
            experience, exp_conf = _extract_experience(raw_text)
            certifications, cert_conf = _extract_certifications(raw_text)
            job_title = _extract_job_title(raw_text, sections)
            keywords = list(dict.fromkeys([*([job_title] if job_title else []), *required_skills, *preferred_skills]))
            domain = _classify_domain(raw_text)
            ai_recovered = False
            important = (job_title, required_skills, education, experience, responsibilities)
            if any(not value for value in important):
                try:
                    recovery = await self.ai_extractor.extract(raw_text)
                except Exception as exc:
                    recovery = None
                    logger.warning("ai_jd_extraction_skipped", document_id=str(document_id), error_type=type(exc).__name__)
                if recovery:
                    recovered_fields = {
                        "job_title": recovery.get("job_title"), "domain": recovery.get("domain"),
                        "required_skills": recovery.get("required_skills", []),
                        "preferred_skills": recovery.get("preferred_skills", []),
                        "responsibilities": recovery.get("responsibilities", []),
                        "education": recovery.get("education", []),
                        "education_disciplines": recovery.get("education_disciplines", []),
                        "experience": recovery.get("experience", []),
                        "certifications": recovery.get("certifications", []),
                        "keywords": recovery.get("keywords", []),
                    }
                    if not job_title and recovered_fields["job_title"]: job_title = recovered_fields["job_title"]
                    if not domain and recovered_fields["domain"]: domain = recovered_fields["domain"]
                    if not required_skills and recovered_fields["required_skills"]: required_skills = recovered_fields["required_skills"]
                    if not preferred_skills and recovered_fields["preferred_skills"]: preferred_skills = recovered_fields["preferred_skills"]
                    if not responsibilities and recovered_fields["responsibilities"]: responsibilities = recovered_fields["responsibilities"]
                    if not education and recovered_fields["education"]: education = recovered_fields["education"]
                    if not education_disciplines and recovered_fields["education_disciplines"]: education_disciplines = recovered_fields["education_disciplines"]
                    if not experience and recovered_fields["experience"]: experience = recovered_fields["experience"]
                    if not certifications and recovered_fields["certifications"]: certifications = recovered_fields["certifications"]
                    if not keywords and recovered_fields["keywords"]: keywords = recovered_fields["keywords"]
                    ai_recovered = True
                    combined_skill_keys = {value.casefold() for value in skills}
                    for value in [*required_skills, *preferred_skills]:
                        if value.casefold() not in combined_skill_keys:
                            skills.append(value)
                            combined_skill_keys.add(value.casefold())

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
                job_title=job_title,
                skills=skills,
                required_skills=required_skills,
                preferred_skills=preferred_skills,
                responsibilities=responsibilities,
                education=education,
                education_disciplines=education_disciplines,
                experience=experience,
                certifications=certifications,
                keywords=keywords,
                confidence_scores=confidence_scores,
                raw_metadata={"source_word_count": parsed.word_count, "ai_recovery": "merged" if ai_recovered else "not_used"},
            )

            try:
                await self.extracted_repository.upsert(
                    payload, commit=False, refresh=False
                )
            except SQLAlchemyError as exc:
                raise InternalServerException("Unable to persist extraction result.") from exc

            updated = await self._set_status(
                document_id,
                ProcessingStatus.COMPLETED,
                {**metadata, "extraction_error": None, "extraction_stage": "EXTRACTION"},
                refresh=False,
                document=document,
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
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        return JDExtractResult(
            document_id=document_id,
            document_type=DocumentType.JOB_DESCRIPTION,
            processing_stage=ProcessingStage.EXTRACTION,
            processing_status=ProcessingStatus.COMPLETED,
            message=f"Extracted {len(skills)} skills, {len(responsibilities)} responsibilities, domain={domain!r}.",
        )

    async def _try_affinda(self, document, metadata: dict) -> JDExtractResult | None:
        if not self.affinda_service.configured:
            return None
        try:
            from app.services.affinda_mapper import map_affinda_jd
            from app.services.affinda_service import AffindaError

            response = (document.metadata_json or {}).get("affinda_payload")
            if not isinstance(response, dict):
                path = self.storage.resolve_file(document.file_path)
                if path is None:
                    raise AffindaError("Stored document is unavailable.")
                response = await self.affinda_service.parse_job_description(
                    path, document.original_filename, document.mime_type
                )
            provider_meta = response.get("meta") or {}
            mapped = map_affinda_jd(
                response["data"], provider_meta.get("identifier")
            )
            await self.extracted_repository.upsert(
                ExtractedJDCreate(document_id=document.id, **mapped),
                commit=False,
                refresh=False,
            )
            await self._set_status(
                document.id,
                ProcessingStatus.COMPLETED,
                {**metadata, "extraction_error": None, "extraction_provider": "affinda"},
                refresh=False,
                document=document,
            )
            logger.info("affinda_jd_succeeded", document_id=str(document.id))
            return JDExtractResult(
                document_id=document.id,
                document_type=DocumentType.JOB_DESCRIPTION,
                processing_stage=ProcessingStage.EXTRACTION,
                processing_status=ProcessingStatus.COMPLETED,
                message="Job Description processed successfully.",
            )
        except Exception as exc:
            logger.warning(
                "affinda_jd_fallback",
                document_id=str(document.id),
                error_type=type(exc).__name__,
            )
            return None

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
        refresh: bool = True,
        document=None,
    ):
        try:
            updated = await self.document_repository.update_status(
                document_id,
                status,
                metadata,
                commit=commit,
                refresh=refresh,
                document=document,
            )
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to update document status.") from exc
        if updated is None:
            raise DocumentNotFoundException()
        return updated
