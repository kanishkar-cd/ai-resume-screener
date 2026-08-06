import re
from collections.abc import Iterable

EMAIL_PATTERN = re.compile(r"[\w.-]+@[\w.-]+\.\w+")
PHONE_PATTERN = re.compile(r"\(?\+?\d{1,4}\)?[\s.-]?\d{3,5}[\s.-]?\d{4}")
URL_PATTERN = re.compile(r"https?://[^\s]+|(?:www\.)[^\s]+", re.IGNORECASE)

SKILLS = (
    "Python", "FastAPI", "SQLAlchemy", "PostgreSQL", "React", "Docker",
    "Pytest", "Java", "JavaScript", "TypeScript", "Django", "Flask",
    "Kubernetes", "Git", "AWS", "Azure", "Node.js", "C++", "SQL",
)
LANGUAGES = (
    "English", "Spanish", "French", "German", "Hindi", "Tamil", "Telugu",
    "Kannada", "Malayalam", "Mandarin", "Japanese", "Arabic",
)
DESIGNATIONS = (
    "Software Engineer", "Backend Engineer", "Frontend Engineer", "Data Engineer",
    "Data Scientist", "DevOps Engineer", "Full Stack Developer", "Python Developer",
    "Product Manager", "Project Manager", "Business Analyst", "QA Engineer",
)
DEGREES = (
    "Bachelor of Science", "Master of Science", "Bachelor of Engineering",
    "Master of Engineering", "B.Tech", "M.Tech", "MBA", "PhD",
)

SECTION_ALIASES = {
    "contact": {"contact", "contact information"},
    "summary": {"summary", "profile", "objective", "professional summary"},
    "skills": {"skills", "technical skills", "core skills", "requirements"},
    "experience": {"experience", "work experience", "work history", "employment"},
    "education": {"education", "academic background", "qualifications"},
    "projects": {"projects", "personal projects", "key projects"},
    "certifications": {"certifications", "certificates", "licenses"},
    "languages": {"languages", "language proficiency"},
    "responsibilities": {"responsibilities", "key responsibilities", "duties"},
    "benefits": {"benefits", "what we offer"},
}


def segment_sections(text: str) -> dict[str, str]:
    """Split normalized text at known standalone section headings."""
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    lookup = {alias: name for name, aliases in SECTION_ALIASES.items() for alias in aliases}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = re.sub(r"[:\s]+$", "", line).casefold()
        if heading in lookup:
            current = lookup[heading]
            sections.setdefault(current, [])
        elif line:
            sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def match_terms(text: str, terms: Iterable[str]) -> list[str]:
    matches: list[str] = []
    for term in terms:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE):
            matches.append(term)
    return matches


def content_lines(text: str) -> list[str]:
    return [
        re.sub(r"^[\s•●▪*\-–—]+", "", line).strip()
        for line in text.splitlines()
        if re.sub(r"^[\s•●▪*\-–—]+", "", line).strip()
    ]


def first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0).strip(" ,.;") if match else None


def field_confidence(value: object, *, strong: bool = False) -> float:
    if value is None or value == "" or value == []:
        return 0.0
    return 0.98 if strong else 0.85
