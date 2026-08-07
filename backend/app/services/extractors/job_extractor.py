import re
from typing import Any

from app.services.pipeline.extraction_pipeline import (
    DEGREES, DESIGNATIONS, SKILLS, content_lines, field_confidence, match_terms,
    segment_sections,
)

EXPERIENCE_PATTERN = re.compile(
    r"\b\d+\+?\s*(?:-|–|to)?\s*\d*\s*years?(?:\s+of\s+experience)?\b", re.I
)
CERTIFICATION_PATTERN = re.compile(r"\b(?:certified|certification|certificate)\b", re.I)
DOMAIN_RULES = {
    "Software Engineering": ("software", "developer", "backend", "frontend", "api"),
    "Data Science": ("data scientist", "machine learning", "analytics"),
    "DevOps": ("devops", "infrastructure", "kubernetes", "ci/cd"),
    "Product Management": ("product manager", "roadmap", "stakeholder"),
}


class JobDescriptionExtractor:
    """Deterministic job-description requirement extractor."""

    def extract(self, text: str) -> dict[str, Any]:
        sections = segment_sections(text)
        skills = match_terms(text, SKILLS)
        responsibilities = content_lines(sections.get("responsibilities", ""))
        education = [line for line in content_lines(sections.get("education", "") or sections.get("skills", "")) if match_terms(line, DEGREES)]
        experience = list(dict.fromkeys(match.group(0) for match in EXPERIENCE_PATTERN.finditer(text)))
        certifications = [line for line in content_lines(sections.get("certifications", "") or text) if CERTIFICATION_PATTERN.search(line)]
        domain = self._domain(text)
        keywords = list(dict.fromkeys([*skills, *match_terms(text, DESIGNATIONS)]))
        values = {
            "domain": domain, "skills": skills, "responsibilities": responsibilities,
            "education": education, "experience": experience,
            "certifications": certifications, "keywords": keywords,
        }
        return {
            **values,
            "confidence_scores": {key: field_confidence(value) for key, value in values.items()},
            "raw_metadata": {"method": "deterministic_rules", "sections": list(sections)},
        }

    @staticmethod
    def _domain(text: str) -> str | None:
        lowered = text.casefold()
        scores = {domain: sum(keyword in lowered for keyword in keywords) for domain, keywords in DOMAIN_RULES.items()}
        best = max(scores, key=scores.get)
        return best if scores[best] else None
