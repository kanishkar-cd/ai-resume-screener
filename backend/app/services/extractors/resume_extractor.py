import re
from typing import Any

from app.services.pipeline.extraction_pipeline import (
    DEGREES, DESIGNATIONS, EMAIL_PATTERN, LANGUAGES, PHONE_PATTERN, SKILLS,
    content_lines, field_confidence, first_match, match_terms, segment_sections,
)

YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
DURATION_PATTERN = re.compile(
    r"\b(?:19|20)\d{2}\s*(?:-|–|—|to)\s*(?:Present|Current|(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
LOCATION_PATTERN = re.compile(r"(?im)^(?:location|address)\s*:\s*(.+)$")
INSTITUTION_PATTERN = re.compile(r"\b(?:University|College|Institute|School)\b", re.I)
COMPANY_PATTERN = re.compile(r"\b(?:Inc\.?|Corp\.?|Corporation|Ltd\.?|LLC|Technologies)\b", re.I)
FIELD_PATTERN = re.compile(
    r"\b(?:Computer Science|Information Technology|Engineering|Business Administration|Data Science)\b",
    re.I,
)


class ResumeExtractor:
    """Deterministic resume extractor using regex, sections, and gazetteers."""

    def extract(self, text: str) -> dict[str, Any]:
        sections = segment_sections(text)
        header = content_lines(sections.get("header", ""))
        candidate_name = self._candidate_name(header)
        email = first_match(EMAIL_PATTERN, text)
        phone = first_match(PHONE_PATTERN, text)
        designation = self._designation(header, text)
        location_match = LOCATION_PATTERN.search(text)
        location = location_match.group(1).strip()[:255] if location_match else None
        skills = match_terms(text, SKILLS)
        education = self._education(sections.get("education", ""))
        experience = self._experience(sections.get("experience", ""))
        projects = self._projects(sections.get("projects", ""))
        certifications = content_lines(sections.get("certifications", ""))
        companies = list(dict.fromkeys(item["company"] for item in experience if item["company"]))
        languages = match_terms(sections.get("languages", ""), LANGUAGES)
        values = {
            "candidate_name": candidate_name, "email": email, "phone": phone,
            "designation": designation, "location": location, "skills": skills,
            "education": education, "experience": experience, "projects": projects,
            "certifications": certifications, "companies": companies, "languages": languages,
        }
        return {
            **values,
            "confidence_scores": {
                key: field_confidence(value, strong=key in {"email", "phone"})
                for key, value in values.items()
            },
            "raw_metadata": {"method": "deterministic_rules", "sections": list(sections)},
        }

    @staticmethod
    def _candidate_name(lines: list[str]) -> str | None:
        for line in lines[:5]:
            words = line.split()
            if 2 <= len(words) <= 5 and not re.search(r"[@\d:/]", line):
                if not match_terms(line, DESIGNATIONS):
                    return line[:255]
        return None

    @staticmethod
    def _designation(header: list[str], text: str) -> str | None:
        matched = match_terms("\n".join(header[:8]), DESIGNATIONS) or match_terms(text, DESIGNATIONS)
        return matched[0] if matched else None

    @staticmethod
    def _education(block: str) -> list[dict[str, str | None]]:
        items = []
        for line in content_lines(block):
            degrees = match_terms(line, DEGREES)
            if degrees or INSTITUTION_PATTERN.search(line):
                year = YEAR_PATTERN.search(line)
                field = FIELD_PATTERN.search(line)
                items.append({
                    "degree": degrees[0] if degrees else None,
                    "institution": line[:255] if INSTITUTION_PATTERN.search(line) else None,
                    "year": year.group(0) if year else None,
                    "field_of_study": field.group(0) if field else None,
                })
        return items

    @staticmethod
    def _experience(block: str) -> list[dict[str, Any]]:
        lines = content_lines(block)
        if not lines:
            return []
        items: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in lines:
            company_match = COMPANY_PATTERN.search(line)
            duration = DURATION_PATTERN.search(line)
            titles = match_terms(line, DESIGNATIONS)
            if company_match or duration or titles:
                if current:
                    items.append(current)
                at_match = re.search(r"\bat\s+(.+?)(?:\s*[|,]|$)", line, re.I)
                current = {
                    "company": (at_match.group(1).strip() if at_match else line[:255]) if company_match else None,
                    "title": titles[0] if titles else None,
                    "duration": duration.group(0) if duration else None,
                    "responsibilities": [],
                }
            elif current:
                current["responsibilities"].append(line)
        if current:
            items.append(current)
        return items

    @staticmethod
    def _projects(block: str) -> list[dict[str, Any]]:
        projects = []
        for line in content_lines(block):
            name, separator, description = line.partition(":")
            projects.append({
                "name": name[:255] or None,
                "description": description.strip() if separator else line,
                "technologies": match_terms(line, SKILLS),
            })
        return projects
