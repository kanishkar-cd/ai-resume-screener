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
        
        # Determine job title if present in header/first line or DESIGNATIONS
        job_title = None
        header_text = sections.get("header", "")
        for line in content_lines(header_text)[:3]:
            matched_desig = match_terms(line, DESIGNATIONS)
            if matched_desig:
                job_title = matched_desig[0]
                break

        # Extracted responsibilities: get responsibilities section strictly
        resp_block = sections.get("responsibilities", "")
        responsibilities = content_lines(resp_block)

        # Education: extract only the degree/qualification names rather than whole sentence
        matched_degrees: list[str] = []
        for sec_name in ("education", "requirements", "skills", "header", "summary"):
            block = sections.get(sec_name, "")
            for line in content_lines(block):
                found = match_terms(line, DEGREES)
                for degree in found:
                    if degree not in matched_degrees:
                        matched_degrees.append(degree)

        if not matched_degrees:
            for line in content_lines(text):
                found = match_terms(line, DEGREES)
                for degree in found:
                    if degree not in matched_degrees:
                        matched_degrees.append(degree)

        education = matched_degrees

        experience = list(dict.fromkeys(match.group(0) for match in EXPERIENCE_PATTERN.finditer(text)))
        certifications = [line for line in content_lines(sections.get("certifications", "") or text) if CERTIFICATION_PATTERN.search(line)]
        domain = self._domain(text)

        # Build keywords list: skills + title/designations + terms from preferred/requirements sections
        title_terms = [job_title] if job_title else match_terms(text, DESIGNATIONS)
        keywords = list(dict.fromkeys([*skills, *title_terms]))

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
