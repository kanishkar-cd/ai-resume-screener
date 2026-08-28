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

# pyrefly: ignore [missing-import]
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
from app.services.pipeline.canonical_dictionaries import SKILL_ALIASES

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
    # Cloud / Infra & Virtualization
    "aws", "azure", "gcp", "google cloud", "heroku", "vercel", "netlify",
    "docker", "kubernetes", "k8s", "helm", "terraform", "ansible", "jenkins",
    "gitlab", "github actions", "ci/cd", "devops", "sre",
    "vmware", "vsphere", "esxi", "vcenter", "hyper-v", "proxmox", "kvm", "virtualization", "openstack",
    # Systems & OS
    "linux", "unix", "windows server", "windows", "redhat", "rhel", "centos", "ubuntu", "debian", "suse",
    # Networking & Protocols
    "dns", "dhcp", "tcp/ip", "vpn", "vlan", "firewall", "routing", "switching", "load balancing", "proxy",
    # Directory & Identity
    "active directory", "directory services", "directory basics", "ldap", "kerberos", "group policy", "gpo", "iam",
    # Storage, Backup & Operations
    "storage", "backup", "recovery", "backup/recovery", "disaster recovery", "san", "nas",
    "monitoring", "observability", "nagios", "zabbix", "prometheus", "grafana", "datadog", "dynatrace", "splunk", "elk", "siem",
    # IT Service Management
    "itil", "itsm", "incident management", "change management", "problem management", "ticketing tools", "servicenow",
    # Certifications & Tools
    "rhcsa", "rhce", "cissp", "ccna", "ccnp", "puppet", "chef", "scripting", "scripting basics", "basic scripting",
    "nginx", "apache", "rabbitmq", "celery", "git", "jira", "confluence", "slack", "figma", "postman", "swagger",
    # Methodologies
    "agile", "scrum", "kanban", "tdd", "bdd", "microservices", "serverless",
    "solid", "clean architecture", "ddd", "event-driven",
    "rest api", "rest apis", "object-oriented programming",
    "data structures and algorithms", "software development and debugging",
    "iot", "embedded systems", "plc programming",
})

CERTIFICATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\baws\s+(?:certified|solutions\s+architect|developer|sysops|devops|administrator)\b",
        r"\bazure\s+(?:certified|fundamentals|associate|expert|administrator)\b",
        r"\bgcp\s+(?:certified|associate|professional)\b",
        r"\brhcsa\b",            # Red Hat Certified System Administrator
        r"\brhce\b",             # Red Hat Certified Engineer
        r"\bitil\b",             # ITIL Certification
        r"\bcka\b",              # Certified Kubernetes Administrator
        r"\bckad\b",             # Certified Kubernetes Application Developer
        r"\bpmp\b",              # Project Management Professional
        r"\bcissp\b",            # Certified Information Systems Security Professional
        r"\bccna\b",             # Cisco Certified Network Associate
        r"\bccnp\b",             # Cisco Certified Network Professional
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
        r"\b(?:bachelor(?:'?s)?|b\.?\s*(?:sc|e|tech|s|com|ca)|undergraduate)\s*(?:degree|of|in)?\s*(?:[a-z\s\&\,]+)?\b",
        r"\b(?:master(?:'?s)?|m\.?\s*(?:sc|e|tech|s|ba|ca)|postgraduate|graduate)\s*(?:degree|of|in)?\s*(?:[a-z\s\&\,]+)?\b",
        r"\b(?:phd|ph\.d|doctorate|doctoral)\b",
        r"\b(?:mba|master\s+of\s+business\s+administration)\b",
        r"\b(?:associate\s+degree)\b",
        r"\b(?:degree|qualification)\s+in\s+[a-z\s\&\,]+(?:\s+or\s+(?:related|equivalent)\s+(?:field|discipline|experience))?\b",
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
        "terraform", "ci/cd", "deployment", "cloud operations", "systems administration",
        "system administrator", "vmware", "active directory",
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

_INVALID_STANDALONE_SKILLS: frozenset[str] = frozenset({
    # Stop words / auxiliary verbs / pronouns / conjunctions / prepositions
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "into", "through", "during", "including",
    "is", "was", "are", "were", "be", "been", "being", "am", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "shall", "can", "need", "this", "that", "these", "those", "it",
    "its", "we", "you", "they", "their", "our", "your", "who", "what",
    "which", "when", "where", "how", "if", "then", "than", "so", "not", "no",
    "nor", "yet", "both", "either", "each", "any", "all", "most", "more",
    "such", "up", "about", "etc", "eg", "ie", "via",
    # Generic JD/Resume meta-words and section words
    "skills", "skill", "basis", "basics", "basic", "requirements", "requirement",
    "required", "qualifications", "qualification", "qualify", "responsibilities",
    "responsibility", "duties", "duty", "knowledge", "experience", "understanding",
    "proficiency", "proficient", "exposure", "familiarity", "concepts", "concept",
    "fundamentals", "fundamental", "principles", "principle",
    "methods", "method", "methodologies", "methodology",
    "applications", "application", "solutions", "solution", "practices", "practice",
    "standards", "standard",
    "plus", "bonus", "advantage", "advantageous", "preferred", "desirable", "desired", "optional", "mandatory",
    "overview", "summary", "description", "details", "candidate", "candidates",
    "role", "roles", "position", "positions", "job", "jobs", "work", "working",
    "team", "teams", "level", "levels", "year", "years", "month", "months",
    "good", "strong", "solid", "deep", "excellent", "proven", "sound",
    "hands-on", "handson",
    # Standalone generic non-skill terms
    "active", "inactive", "log", "logs", "analysis", "analytics",
    "triage", "findings", "policies", "procedures",
})

BULLET_PATTERN = re.compile(r"^[\s]*[-•*►▸▶·‣⁃◆○●✦✧★☆✱*]+\s+", re.MULTILINE)
NUMBERED_PATTERN = re.compile(r"^[\s]*\d+[.)]\s+", re.MULTILINE)

SECTION_HEADINGS = {
    # Description / Summary / About
    "job description": "description", "overview": "description", "summary": "description",
    "role overview": "description", "position summary": "description", "role summary": "description",
    "job summary": "description", "about the role": "description", "about the job": "description",
    "about us": "description", "company overview": "description", "position overview": "description",
    # Responsibilities
    "key responsibilities": "responsibilities", "responsibilities": "responsibilities",
    "duties": "responsibilities", "job responsibilities": "responsibilities",
    "core responsibilities": "responsibilities", "key duties": "responsibilities",
    "role responsibilities": "responsibilities", "what you will do": "responsibilities",
    "what you'll do": "responsibilities", "primary responsibilities": "responsibilities",
    "essential duties": "responsibilities", "essential functions": "responsibilities",
    # Required Skills & Requirements
    "required technical skills": "required_skills", "technical skills": "required_skills",
    "required skills": "required_skills", "required qualifications": "required_skills",
    "requirements": "required_skills", "key requirements": "required_skills",
    "core skills": "required_skills", "skills required": "required_skills",
    "qualifications": "required_skills", "basic qualifications": "required_skills",
    "technical requirements": "required_skills", "key technical skills": "required_skills",
    "core technical skills": "required_skills", "technical competencies": "required_skills",
    "skills & requirements": "required_skills", "skills and requirements": "required_skills",
    "skills and qualifications": "required_skills", "skills & qualifications": "required_skills",
    "must have skills": "required_skills", "must have": "required_skills",
    "must-have": "required_skills", "minimum qualifications": "required_skills",
    "minimum requirements": "required_skills", "technical expertise": "required_skills",
    # Preferred Skills
    "preferred skills": "preferred_skills", "nice to have": "preferred_skills",
    "preferred qualifications": "preferred_skills", "desired skills": "preferred_skills",
    "bonus skills": "preferred_skills", "good to have": "preferred_skills",
    "additional qualifications": "preferred_skills", "desired qualifications": "preferred_skills",
    "preferred requirements": "preferred_skills", "nice-to-have": "preferred_skills",
    # Education & Experience
    "education": "education", "education requirements": "education",
    "educational qualifications": "education", "academic background": "education",
    "education & experience": "education", "education and experience": "education",
    "experience": "experience", "experience required": "experience",
    "work experience": "experience", "experience & education": "experience",
    "experience and education": "experience",
    # Certifications & Keywords
    "certifications": "certifications", "licenses": "certifications", "credentials": "certifications",
    "certifications & licenses": "certifications", "certifications and licenses": "certifications",
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
    "Active Directory": ("active directory", "ad", "directory basics", "directory services", "active directory basics"),
    "Scripting basics": ("scripting basics", "basic scripting", "shell scripting", "script automation", "task automation", "command-line scripting"),
    "Windows Server": ("windows server", "windows server administration"),
    "VMware": ("vmware", "vsphere", "esxi", "vcenter"),
    "TCP/IP": ("tcp/ip",),
    "DNS": ("dns",),
    "DHCP": ("dhcp",),
    "ITIL": ("itil", "itsm"),
    "Storage": ("storage", "san", "nas"),
    "Monitoring": ("monitoring", "observability"),
    "Backup/Recovery": ("backup/recovery", "backup and recovery", "backup", "recovery", "disaster recovery"),
    "Incident Management": ("incident management", "incident/change management"),
    "Change Management": ("change management",),
    "MERN": ("mern", "mern stack"),
    "JWT": ("jwt", "json web token", "json web tokens"),
    "HTML5": ("html5",), "CSS3": ("css3",),
    "React Testing Library": ("react testing library", "react-testing-library", "rtl"),
    "Redux Toolkit": ("redux toolkit", "rtk", "redux-toolkit"),
    "Next.js": ("next.js", "nextjs", "next"),
    "GraphQL": ("graphql",),
    "Redis": ("redis",),
    "TypeScript": ("typescript", "ts"),
    "Jest": ("jest",),
    "WebSockets": ("websockets", "websocket", "ws"),
    "Microservices": ("microservices", "microservice", "microservice architecture"),
    "GitHub": ("github",),
    "GitLab": ("gitlab",),
}


_CATEGORY_LABEL_PREFIX = re.compile(
    r"^(?:frontend|backend|database|databases|engineering|tools|tooling|languages|programming\s+languages|frameworks|libraries|devops|cloud|infrastructure|testing|qa|platforms|methodologies|architecture|security|storage|monitoring|web|mobile|data|analytics|core|technical|key|other)\s*:\s*",
    re.I,
)


def _canonicalize_skill_name(skill: str) -> str:
    """Return the standard canonical name for a skill if known, else original cleaned string."""
    cleaned = _clean_skill_term(skill)
    # Preserve compound slash alternatives intact without flattening
    if "/" in cleaned or "|" in cleaned:
        return cleaned
    key = cleaned.casefold()
    for canonical_name, aliases in SKILL_CANONICAL.items():
        if key == canonical_name.casefold() or key in {a.casefold() for a in aliases}:
            return canonical_name
    return cleaned

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
        clean_line = BULLET_PATTERN.sub("", line)
        clean_line = NUMBERED_PATTERN.sub("", clean_line).strip()
        prefix, separator, remainder = clean_line.partition(":")
        candidate = re.sub(r"\s+", " ", prefix if separator else clean_line).strip().casefold()
        candidate = re.sub(r"^[^\w]+|[^\w]+$", "", candidate)
        heading = SECTION_HEADINGS.get(candidate) if len(candidate) <= 60 else None
        if heading:
            current = heading
            sections.setdefault(current, [])
            if separator and remainder.strip():
                sections[current].append(remainder.strip())
        else:
            sections.setdefault(current, []).append(line)
    return {key: "\n".join(lines) for key, lines in sections.items()}


_FILLER_TRAILERS = re.compile(
    r"\b(?:(?:is|are|will\s+be|would\s+be|can\s+be)?\s*(?:an?\s+)?(?:advantage|plus|bonus|preferred|required|mandatory|optional|beneficial|welcome|welcomed|desirable|desired|asset|good\s+to\s+have|nice\s+to\s+have|or\s+equivalent|or\s+similar|or\s+related))\b\.?",
    re.I,
)
_FILLER_LEADERS = re.compile(
    r"^(?:(?:strong|solid|deep|basic|general|good|sound|proven|demonstrated|prior|hands[-\s]on)\s+)?(?:exposure\s+to|knowledge\s+of|understanding\s+of|experience\s+with|experience\s+in|proficiency\s+in|hands[-\s]on\s+experience\s+with|ability\s+to|familiarity\s+with|skills\s+in|working\s+knowledge\s+of|background\s+in|foundation\s+in|competency\s+in|expertise\s+in|must\s+have|should\s+have|required:\s*|preferred:\s*)\s*",
    re.I,
)
_ACTION_VERB_LEADERS = re.compile(
    r"^(?:(?:to\s+)?(?:"
    r"develop|developed|developing|"
    r"design|designed|designing|"
    r"build|built|building|"
    r"implement|implemented|implementing|"
    r"create|created|creating|"
    r"architect|architected|architecting|"
    r"lead|led|leading|"
    r"manage|managed|managing|"
    r"coordinate|coordinated|coordinating|"
    r"collaborate|collaborated|collaborating|"
    r"maintain|maintained|maintaining|"
    r"optimize|optimized|optimizing|"
    r"improve|improved|improving|"
    r"deploy|deployed|deploying|"
    r"monitor|monitored|monitoring|"
    r"integrate|integrated|integrating|"
    r"test|tested|testing|"
    r"review|reviewed|reviewing|"
    r"write|wrote|writing|"
    r"deliver|delivered|delivering|"
    r"drive|drove|driving|"
    r"ensure|ensured|ensuring|"
    r"establish|established|establishing|"
    r"define|defined|defining|"
    r"evaluate|evaluated|evaluating|"
    r"work|worked|working|"
    r"use|used|using|"
    r"contribute|contributed|contributing|"
    r"analyze|analyzed|analyzing|"
    r"research|researched|researching|"
    r"document|documented|documenting|"
    r"support|supported|supporting|"
    r"troubleshoot|troubleshot|troubleshooting|"
    r"mentor|mentored|mentoring|"
    r"administer|administered|administering|"
    r"automate|automated|automating|"
    r"configure|configured|configuring|"
    r"participate|participated|participating|"
    r"translate|translated|translating|"
    r"fix|fixed|fixing|"
    r"resolve|resolved|resolving|"
    r"perform|performed|performing|"
    r"assist|assisted|assisting|"
    r"handle|handled|handling|"
    r"triage|triaged|triaging|"
    r"execute|executed|executing|"
    r"provide|provided|providing|"
    r"responsible\s+for|duties\s+include|in\s+this\s+role|you\s+will|ability\s+to"
    r")\b)",
    re.IGNORECASE,
)

_GRAMMATICAL_FRAGMENTS = re.compile(
    r"^(?:or|and|is|are|were|was|be|an|a|the|concepts?|language|frameworks?|tools?|systems?|methods?|basis|requirements?|skills?)\.?$",
    re.I,
)

_PROSE_SENTENCE_PATTERNS = re.compile(
    r"^(?:we\s+are\s+(?:seeking|looking|hiring)|the\s+role\s+(?:focuses|requires|involves|is)|as\s+(?:a|an)|you\s+will\s+(?:be|work|have)|this\s+position\s+(?:is|will|requires)|our\s+team\s+is|join\s+our|responsible\s+for|in\s+this\s+role)\b",
    re.I,
)


def _is_action_sentence(line: str) -> bool:
    """Check if a line represents an action, duty, or responsibility sentence rather than a skill listing."""
    cleaned = line.strip()
    words = cleaned.split()
    if not words:
        return False
    if len(words) >= 3 and _ACTION_VERB_LEADERS.match(cleaned):
        if cleaned.casefold() in {"software development and debugging", "software development & debugging"}:
            return False
        return True
    return False


def _is_project_clause(line: str) -> bool:
    """Check if a line represents a project description or project capability statement."""
    cleaned = line.strip()
    if re.search(r"^[A-Za-z0-9\s\.\-]+\s+[—–-]\s+(?:developed|built|created|designed|implemented|features)\b", cleaned, re.I):
        return True
    if re.search(r"\b(?:features\s+using|application\s+using|developed\s+product\s+listing|order-management\s+features)\b", cleaned, re.I):
        return True
    return False


def _extract_embedded_skills(text: str) -> list[str]:
    """Extract recognized technical skills embedded within project or responsibility sentences."""
    found: list[str] = []
    seen: set[str] = set()
    lowered = text.casefold()

    for canonical_name, aliases in SKILL_CANONICAL.items():
        all_terms = [canonical_name, *aliases]
        for term in all_terms:
            pattern = r"(?:\b|_)" + re.escape(term.casefold()) + r"(?:\b|_)"
            if re.search(pattern, lowered):
                key = canonical_name.casefold()
                if key not in seen:
                    seen.add(key)
                    found.append(canonical_name)
                break

    return found


def _is_valid_skill(skill: str) -> bool:
    """Validate whether an extracted skill phrase is a legitimate requirement."""
    if not skill or not isinstance(skill, str):
        return False
    cleaned = skill.strip()
    if len(cleaned) < 2 and cleaned.upper() not in {"C", "R"}:
        return False
    if len(cleaned) > 60:
        return False
    if not re.search(r"[a-zA-Z]", cleaned):
        return False

    if _PROSE_SENTENCE_PATTERNS.search(cleaned):
        return False

    # Filter action / responsibility sentences
    if _is_action_sentence(cleaned) or _is_project_clause(cleaned):
        return False

    words = cleaned.split()
    lower = cleaned.casefold()

    if lower in _INVALID_STANDALONE_SKILLS:
        return False

    # Check if single word is an invalid fragment
    if len(words) == 1 and lower in _INVALID_STANDALONE_SKILLS:
        return False

    if _GRAMMATICAL_FRAGMENTS.match(cleaned):
        return False

    return True


def _clean_skill_term(term: str) -> str:
    cleaned = term.strip()
    cleaned = _CATEGORY_LABEL_PREFIX.sub("", cleaned).strip()
    cleaned = _FILLER_TRAILERS.sub("", cleaned).strip()
    cleaned = _FILLER_LEADERS.sub("", cleaned).strip()
    cleaned = _CATEGORY_LABEL_PREFIX.sub("", cleaned).strip()
    # Remove leading filler/auxiliary words or punctuation
    cleaned = re.sub(r"^(?:or|and|with|in|of|to|for|on|at|by|from|as|including|such\s+as|are|is|be)\s+", "", cleaned, flags=re.I).strip()
    # Remove trailing filler/auxiliary words or punctuation
    cleaned = re.sub(r"\s+(?:or|and|with|in|of|to|for|on|at|by|from|as|are|is|be|etc|a\s+plus|plus|an\s+advantage|advantage|bonus|preferred|required)$", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s+(?:or\s+similar|or\s+equivalent|or\s+related)$", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^[^\w\+\#]+|[^\w\+\#\.]+$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _split_sentence_into_skills(sentence: str) -> list[str]:
    """
    Parse requirement sentences structurally:
    - Splits across clause/sentence period boundaries.
    - Splits on comma and semicolon boundaries.
    - Preserves slash alternative groups intact (e.g. 'Selenium/Playwright/Cypress', 'Java/Python/JavaScript', 'Agile/Scrum', 'Linux/Windows Server') as single requirements.
    """
    results: list[str] = []
    clauses = [c.strip() for c in re.split(r"\.\s+", sentence) if c.strip()]
    for clause in clauses:
        clause_clean = clause.rstrip(".")
        clause_clean = _CATEGORY_LABEL_PREFIX.sub("", clause_clean).strip()
        stripped_clause = _FILLER_LEADERS.sub("", clause_clean).strip()
        stripped_clause = _FILLER_TRAILERS.sub("", stripped_clause).strip()
        stripped_clause = _CATEGORY_LABEL_PREFIX.sub("", stripped_clause).strip()

        # Split on semicolon or comma
        if "," in stripped_clause or ";" in stripped_clause:
            items = re.split(r"[,;]\s*", stripped_clause)
        else:
            items = [stripped_clause]

        for item in items:
            item_clean = _clean_skill_term(item)
            if item_clean and _is_valid_skill(item_clean):
                results.append(item_clean)

    return results


def _canonical_skills(text: str, extra_responsibilities: list[str] | None = None) -> list[str]:
    """Extract atomic and compound requirements as specified in the JD text, cleanly separating responsibilities and projects."""
    if not text.strip():
        return []
    terms: list[str] = []
    seen: set[str] = set()

    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
    if ";" in text and not re.search(r"^[•\-\*]", text, re.MULTILINE):
        lines = [re.sub(r"\n+", " ", text).strip()]
    else:
        lines: list[str] = []
        for line in raw_lines:
            if lines and not line.startswith(("-", "*", "•")) and (
                lines[-1].endswith((",", ";", "/", "-")) or 
                ("," in lines[-1] and not lines[-1].endswith(".") and len(line.split()) <= 4)
            ):
                lines[-1] = f"{lines[-1]} {line}"
            else:
                lines.append(line)

    for line in lines:
        cleaned_line = BULLET_PATTERN.sub("", line)
        cleaned_line = NUMBERED_PATTERN.sub("", cleaned_line).strip()
        if not cleaned_line or re.match(r"^(?:required|preferred|technical|core|key)?\s*skills?:?$", cleaned_line, re.I):
            continue

        # If line is an action responsibility or project description, route to responsibilities and extract embedded skills
        if _is_action_sentence(cleaned_line) or _is_project_clause(cleaned_line):
            if extra_responsibilities is not None and len(cleaned_line) > 15:
                extra_responsibilities.append(cleaned_line)

            embedded = _extract_embedded_skills(cleaned_line)
            for skill in embedded:
                canonical = _canonicalize_skill_name(skill)
                key = canonical.casefold()
                if key not in seen and len(canonical) <= 80:
                    seen.add(key)
                    terms.append(canonical)
            continue

        extracted = _split_sentence_into_skills(cleaned_line)
        for skill in extracted:
            if _is_valid_skill(skill):
                canonical = _canonicalize_skill_name(skill)
                key = canonical.casefold()
                if key not in seen and len(canonical) <= 80:
                    seen.add(key)
                    terms.append(canonical)
    return terms


def _extract_job_title(text: str, sections: dict[str, str]) -> str | None:
    match = re.search(r"(?im)^\s*(?:job\s*title|position|role|title)\s*:\s*([^\n]{2,80})$", text)
    if match:
        return match.group(1).strip()
    for line in text.splitlines()[:5]:
        stripped = line.strip()
        if stripped and len(stripped) < 60 and not re.search(r"\b(?:requirements|responsibilities|qualifications|about\s+us|description|location|salary)\b", stripped, re.I):
            return stripped
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
    """Extract bullet-point / list items directly from responsibilities section text."""
    responsibilities: list[str] = []
    seen: set[str] = set()

    for line in text.splitlines():
        cleaned = BULLET_PATTERN.sub("", line)
        cleaned = NUMBERED_PATTERN.sub("", cleaned).strip()
        if len(cleaned) > 15:
            key = cleaned.casefold()
            if key not in seen and not re.match(r"^(?:key\s+)?responsibilities:?$", key, re.I):
                seen.add(key)
                responsibilities.append(cleaned)

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
            extra_resp: list[str] = []
            required_skills = _canonical_skills(sections.get("required_skills", ""), extra_responsibilities=extra_resp)
            preferred_skills = _canonical_skills(sections.get("preferred_skills", ""), extra_responsibilities=extra_resp)

            # If required_skills is empty because the JD has no explicit "Required Skills:" heading,
            # extract skills from header / unsectioned lines with list or delimiter structures
            if not required_skills:
                header_text = sections.get("header", "")
                candidate_lines = []
                for line in header_text.splitlines():
                    l_str = line.strip()
                    if ";" in l_str or ("," in l_str and not l_str.startswith("http") and len(l_str.split(",")) >= 2):
                        candidate_lines.append(l_str)
                if candidate_lines:
                    required_skills = _canonical_skills("\n".join(candidate_lines), extra_responsibilities=extra_resp)

            combined_skill_keys = {value.casefold() for value in skills}
            for value in [*required_skills, *preferred_skills]:
                if value.casefold() not in combined_skill_keys:
                    skills.append(value)
                    combined_skill_keys.add(value.casefold())
            responsibility_source = sections.get("responsibilities", "")
            responsibilities, resp_conf = _extract_responsibilities(responsibility_source) if responsibility_source else ([], 0.0)
            for r in extra_resp:
                if r not in responsibilities and len(r) > 15:
                    responsibilities.append(r)
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

            required_skills = [s for s in required_skills if _is_valid_skill(s)]
            preferred_skills = [s for s in preferred_skills if _is_valid_skill(s)]
            skills = [s for s in skills if _is_valid_skill(s)]

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

            logger.info(
                "jd_pipeline_trace",
                document_id=str(document_id),
                raw_jd_text_snippet=raw_text[:200],
                affinda_used=affinda_result is not None,
                ai_used=ai_recovered,
                extracted_skills=skills,
                extracted_required_skills=required_skills,
                extracted_responsibilities=responsibilities[:3],
                extracted_experience=experience,
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
            if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
                return None

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
