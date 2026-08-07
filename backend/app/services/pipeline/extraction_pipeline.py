import re
from collections.abc import Iterable

EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_PATTERN = re.compile(
    r"(?:\+\d{1,3}[\s.-]*)?\(?\d{2,5}\)?[\s.-]*\d{3,5}[\s.-]*\d{3,5}\b|\b[6-9]\d{9}\b"
)
URL_PATTERN = re.compile(r"https?://[^\s]+|(?:www\.)[^\s]+", re.IGNORECASE)

SKILLS = (
    "Python", "FastAPI", "SQLAlchemy", "PostgreSQL", "React", "Docker",
    "Pytest", "Java", "JavaScript", "TypeScript", "Django", "Flask",
    "Kubernetes", "Git", "AWS", "Azure", "Node.js", "Node", "C++", "SQL",
    "HTML", "CSS", "MongoDB", "Jenkins", "Terraform", "DynamoDB", "Redis",
    "Lambda", "API Gateway", "S3", "EC2", "GraphQL", "REST API", "Linux",
    "GitLab", "CI/CD", "GCP", "Go", "Spring Boot", "Express", "Vue",
    "Angular", "Next.js", "Tailwind", "Kafka", "Elasticsearch", "RabbitMQ",
    "Rust", "C#", ".NET", "Redux", "Pandas", "NumPy", "Scikit-learn",
    "TensorFlow", "PyTorch", "Bash", "Shell", "MySQL", "SQLite", "Oracle",
)

LANGUAGES = (
    "English", "Spanish", "French", "German", "Hindi", "Tamil", "Telugu",
    "Kannada", "Malayalam", "Marathi", "Mandarin", "Japanese", "Arabic",
)

DESIGNATIONS = tuple(
    sorted(
        (
            "Senior Software Engineer", "Senior Backend Engineer", "Senior Frontend Engineer",
            "Senior Full Stack Engineer", "Senior Data Engineer", "Senior DevOps Engineer",
            "Database Management Intern", "Software Engineer Intern", "Database Intern",
            "Software Engineer", "Backend Engineer", "Frontend Engineer", "Full Stack Engineer",
            "Data Engineer", "Data Scientist", "DevOps Engineer", "Lead Engineer", "Tech Lead",
            "Software Developer", "Python Developer", "Java Developer", "Full Stack Developer",
            "Frontend Developer", "Backend Developer", "Product Manager", "Project Manager",
            "Business Analyst", "QA Engineer", "System Administrator", "Solutions Architect",
            "Intern", "Engineering Manager", "Technical Lead",
        ),
        key=len,
        reverse=True,
    )
)

DEGREES = tuple(
    sorted(
        (
            "Bachelor of Technology in Artificial Intelligence and Data Science",
            "Bachelor of Technology in Computer Science",
            "Bachelor of Science in Computer Science",
            "Bachelor of Science", "Master of Science", "Bachelor of Engineering",
            "Master of Engineering", "Bachelor of Technology", "Master of Technology",
            "B.Tech", "M.Tech", "B.E.", "M.E.", "B.S.", "M.S.", "B.Sc", "M.Sc",
            "BCA", "MCA", "B.A.", "B.Com", "MBA", "PhD", "Doctor of Philosophy",
            "Associate Degree", "High School",
        ),
        key=len,
        reverse=True,
    )
)

SECTION_ALIASES = {
    "contact": {"contact", "contact information", "personal info", "personal details"},
    "summary": {"summary", "profile", "objective", "professional summary", "about me", "executive summary"},
    "skills": {"skills", "technical skills", "core skills", "core competencies", "skills & tools", "technologies", "key skills"},
    "requirements": {"requirements", "required skills", "job requirements", "prerequisites"},
    "experience": {
        "experience", "work experience", "professional experience", "work history",
        "employment", "employment history", "career history", "relevant experience",
        "internship", "internships", "internship experience",
        "intership", "interships",
    },
    "education": {"education", "academic background", "academic qualifications", "qualifications", "education & qualifications"},
    "projects": {"projects", "personal projects", "key projects", "academic projects", "selected projects", "technical projects"},
    "certifications": {
        "certifications", "certificates", "licenses", "certifications & licenses",
        "licenses & certifications", "trainings", "training & certifications",
        "courses", "workshops", "online courses",
    },
    "awards": {"awards", "honors", "achievements", "awards & honors", "awards & achievements"},
    "publications": {"publications", "research publications", "papers"},
    "languages": {"languages", "language proficiency", "languages known"},
    "responsibilities": {"responsibilities", "key responsibilities", "duties"},
    "benefits": {"benefits", "what we offer"},
}


def clean_unicode(text: str) -> str:
    """Normalize Unicode by stripping zero-width spaces, soft hyphens, and non-breaking spaces."""
    if not text:
        return ""
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
    text = text.replace("\u00a0", " ")
    return text


def reconstruct_layout_text(text: str) -> str:
    """Detect layout structure and reconstruct reading order for multi-column / interleaved text."""
    cleaned = clean_unicode(text)
    lines = cleaned.splitlines()
    if not lines:
        return ""

    col1_lines: list[str] = []
    col2_lines: list[str] = []
    interleaved_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if "   " in stripped or " | " in stripped:
            parts = re.split(r"\s{3,}|\s*\|\s*", stripped, maxsplit=1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                interleaved_count += 1
                col1_lines.append(parts[0].strip())
                col2_lines.append(parts[1].strip())
                continue
        col1_lines.append(stripped)

    if len(lines) > 4 and (interleaved_count / len(lines)) >= 0.25:
        return "\n".join(col1_lines) + "\n\n" + "\n".join(col2_lines)

    return "\n".join(lines)


def segment_sections(text: str) -> dict[str, str]:
    """Split normalized text hierarchically at known section headings."""
    reconstructed_text = reconstruct_layout_text(text)
    sections: dict[str, list[str]] = {"header": []}
    current = "header"

    alias_map: dict[str, str] = {}
    for canonical, aliases in SECTION_ALIASES.items():
        for alias in aliases:
            alias_map[alias.lower()] = canonical

    for raw_line in reconstructed_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        clean_heading = re.sub(r"^[#*•\s-]+", "", line)
        clean_heading = re.sub(r"[:\s_=-]+$", "", clean_heading).strip().lower()

        matched_section = alias_map.get(clean_heading)

        if not matched_section:
            heading_words = len(clean_heading.split())
            for alias, canonical in alias_map.items():
                alias_words = len(alias.split())
                # Only fire fuzzy match if:
                #   1. The heading is short (≤4 words) — likely a standalone heading
                #   2. OR the alias covers the majority of heading words
                if heading_words <= 4 or alias_words >= (heading_words // 2 + 1):
                    if re.search(rf"\b{re.escape(alias)}\b", clean_heading):
                        if len(clean_heading.split()) <= 6:
                            matched_section = canonical
                            break

        if matched_section and matched_section != current:
            current = matched_section
            sections.setdefault(current, [])
        elif matched_section and matched_section == current:
            # Same section re-triggered — treat as content, not a heading
            sections.setdefault(current, []).append(line)
        else:
            sections.setdefault(current, []).append(line)

    return {name: "\n".join(lines) for name, lines in sections.items()}


def match_terms(text: str, terms: Iterable[str]) -> list[str]:
    cleaned_text = clean_unicode(text)
    matches: list[str] = []
    for term in terms:
        escaped = re.escape(term)
        pattern = rf"(?<![\w#+.]){escaped}(?![\w#+.])"
        if re.search(pattern, cleaned_text, re.IGNORECASE):
            matches.append(term)
    return matches


def content_lines(text: str) -> list[str]:
    cleaned_text = clean_unicode(text)
    return [
        re.sub(r"^[\s•●▪*–—-]+", "", line).strip()
        for line in cleaned_text.splitlines()
        if re.sub(r"^[\s•●▪*–—-]+", "", line).strip()
    ]


def first_match(pattern: re.Pattern[str], text: str) -> str | None:
    cleaned_text = clean_unicode(text)
    match = pattern.search(cleaned_text)
    return match.group(0).strip(" ,.;:()") if match else None


def field_confidence(value: object, *, strong: bool = False) -> float:
    if value is None or value == "" or value == []:
        return 0.0
    if isinstance(value, list):
        count = len(value)
        if count == 0:
            return 0.0
        return min(0.99, 0.85 + (count * 0.03))
    if isinstance(value, str):
        return 0.98 if strong else 0.95
    return 0.90
