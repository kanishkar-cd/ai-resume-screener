import re
from datetime import UTC, date, datetime
from typing import Any

# pyrefly: ignore [missing-import]
import structlog

from app.services.pipeline.canonical_dictionaries import RULESET_VERSION

logger = structlog.get_logger(__name__)


_SKILL_SUFFIX = re.compile(r"\s*\((?:programming language)\)\s*$", re.IGNORECASE)
_SKILL_ALIASES = {
    "cascading style sheets (css)": "CSS",
    "express.js (javascript library)": "Express.js",
    "git (version control system)": "Git",
    "html scripting": "HTML",
    "node.js (javascript library)": "Node.js",
    "react.js (javascript library)": "React.js",
    "restful api": "REST API",
}


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _skill_name(item: Any, source_text: str | None = None) -> str | None:
    value = item.get("name") if isinstance(item, dict) else item
    value = _text(value)
    if not value:
        return None
    canonical = _SKILL_SUFFIX.sub("", value)
    alias = _SKILL_ALIASES.get(value.casefold())
    if alias:
        return alias
    source = source_text or ""
    if value.casefold() == "application programming interface (api)":
        return "REST API" if re.search(r"\brest(?:ful)?\s+apis?\b", source, re.IGNORECASE) else "Application Programming Interface"
    if value.casefold() == "data structures":
        if re.search(r"\bdsa\b", source, re.IGNORECASE):
            return "DSA"
    if value.casefold() in {"object-oriented programming (oop)", "object oriented programming", "oop"}:
        if re.search(r"\boop\b", source, re.IGNORECASE):
            return "OOP"
        return "Object-Oriented Programming"
    if source and len(source.strip()) > 50:
        clean_cand = re.sub(r"[^\w\s+#.]", "", canonical).strip()
        if len(clean_cand) >= 3:
            pattern = rf"(?:\b|_){re.escape(clean_cand)}(?:\b|_)"
            if not re.search(pattern, source, re.IGNORECASE):
                orig_raw = re.sub(r"[^\w\s+#.]", "", value).strip()
                if not re.search(rf"(?:\b|_){re.escape(orig_raw)}(?:\b|_)", source, re.IGNORECASE):
                    return None
    return canonical


def _source_project_descriptions(
    projects: list[dict[str, Any]], source_text: str | None
) -> dict[int, str]:
    """Pair exact Affinda project titles with their source-text descriptions."""
    if not source_text or not projects:
        return {}

    first_title = _text(projects[0].get("projectTitle"))
    if not first_title:
        return {}
    first_title_match = re.search(re.escape(first_title), source_text, re.IGNORECASE)
    if not first_title_match:
        return {}

    # Affinda flattens PDF layout into one line. Anchor the section heading to
    # the first structured project title instead of accepting prose such as
    # "real-world web projects" earlier in the resume.
    heading_matches = [
        match
        for match in re.finditer(r"\bPROJECTS?\b", source_text)
        if match.end() <= first_title_match.start()
    ]
    if not heading_matches:
        return {}
    section = source_text[heading_matches[-1].end():]

    matches: list[tuple[int, int, int]] = []
    cursor = 0
    for index, project in enumerate(projects):
        title = _text(project.get("projectTitle"))
        if not title:
            continue
        match = re.search(re.escape(title), section[cursor:], re.IGNORECASE)
        if not match:
            return {}
        start, end = cursor + match.start(), cursor + match.end()
        matches.append((index, start, end))
        cursor = end

    # Major headings in Affinda rawText preserve uppercase even when line
    # breaks are flattened. Case-sensitive matching prevents ordinary prose
    # words such as "skills" from ending the project section.
    last_title_end = matches[-1][2]
    boundary = re.search(
        r"\b(?:CERTIFICATIONS?|ACHIEVEMENTS?|CODING PROFILES?|EDUCATION|SKILLS)\b",
        section[last_title_end:],
    )
    if boundary:
        section = section[:last_title_end + boundary.start()]

    descriptions: dict[int, str] = {}
    for position, (index, _, title_end) in enumerate(matches):
        next_start = matches[position + 1][1] if position + 1 < len(matches) else len(section)
        description = section[title_end:next_start]
        description = re.sub(
            r"^\s*(?:[-–—]\s*)?(?:19|20)\d{2}\s*", "", description
        ).strip(" \t\r\n-–—")
        if description:
            descriptions[index] = description
    return descriptions


def _map_projects(items: Any, source_text: str | None) -> list[dict[str, Any]]:
    raw_projects = [item for item in (items or []) if isinstance(item, dict)]
    source_descriptions = _source_project_descriptions(raw_projects, source_text)
    mapped: list[dict[str, Any]] = []
    for index, item in enumerate(raw_projects):
        explicit = item.get("technologies") or item.get("skills") or []
        raw_title = _text(item.get("projectTitle"))
        mapped.append({
            "name": raw_title.rstrip(" -–—") if raw_title else None,
            "description": source_descriptions.get(index) or _text(item.get("projectDescription")),
            "technologies": _unique([
                value for entry in explicit
                if (value := _skill_name(entry, source_text))
            ]),
        })

    # Some Affinda responses collapse one description per project into newline-
    # separated text on the first item. Preserve ordering when source text is not
    # available and that relationship is unambiguous.
    if not source_descriptions and len(mapped) > 1:
        descriptions = (mapped[0].get("description") or "").splitlines()
        descriptions = [value.strip() for value in descriptions if value.strip()]
        if len(descriptions) == len(mapped) and all(
            not project.get("description") for project in mapped[1:]
        ):
            for project, description in zip(mapped, descriptions, strict=True):
                project["description"] = description
    if not mapped and source_text:
        from app.services.extractors.resume_extractor import ResumeExtractor
        from app.services.pipeline.extraction_pipeline import reconstruct_layout_text, segment_sections
        layout_text = reconstruct_layout_text(source_text)
        sections = segment_sections(layout_text)
        extracted_projs = ResumeExtractor._projects(sections.get("projects", ""))
        if not extracted_projs and sections.get("experience", ""):
            extracted_projs = ResumeExtractor._extract_embedded_projects(sections.get("experience", ""))
        if extracted_projs:
            return extracted_projs
    return mapped


def _date_value(value: Any) -> str | None:
    if isinstance(value, dict):
        return _text(value.get("date"))
    return _text(value)


def _months(start: str | None, end: str | None, current: bool = False) -> int | None:
    if not start:
        return None
    try:
        start_date = date.fromisoformat(start[:10])
        end_date = date.today() if current or not end else date.fromisoformat(end[:10])
    except ValueError:
        return None
    return max(0, (end_date.year - start_date.year) * 12 + end_date.month - start_date.month)


def map_affinda_resume(data: dict[str, Any], provider_id: str | None = None, source_text: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    logger.info("[MAPPER] Affinda resume mapper started")
    name = data.get("candidateName") or {}
    candidate_name = " ".join(filter(None, [_text(name.get("firstName")), _text(name.get("middleName")), _text(name.get("familyName"))])) or None
    skills = _unique([value for item in data.get("skill") or [] if (value := _skill_name(item, source_text))])
    education, normalized_education, misclassified_certs = [], [], []
    for item in data.get("education") or []:
        if not isinstance(item, dict):
            continue
        majors = item.get("educationMajor") or []
        major = _text(majors[0] if isinstance(majors, list) and majors else majors)
        degree_raw = _text(item.get("educationAccreditation"))
        institution = _text(item.get("educationOrganization"))
        if (institution and any(prov in institution.lower() for prov in ["infosys", "coursera", "udemy", "edx", "skillrack", "springboard"])) or (
            degree_raw and any(prov in degree_raw.lower() for prov in ["introduction to python", "python for data science"])
        ):
            cert_name = f"{degree_raw} - {institution}" if degree_raw and institution else (degree_raw or institution)
            if cert_name:
                misclassified_certs.append(cert_name)
            continue
        degrees = [d.strip() for d in degree_raw.split(",") if d.strip()] if degree_raw else [None]
        for degree in degrees:
            education.append({"degree": degree, "institution": institution, "field_of_study": major})
            normalized_education.append({"degree": degree, "institution": institution, "field_of_study": major, "graduation_date": None})
    experience, normalized_experience, companies, titles = [], [], [], []
    for item in data.get("workExperience") or []:
        if not isinstance(item, dict):
            continue
        dates = item.get("workExperienceDates") or {}
        start_node, end_node = dates.get("start") or {}, dates.get("end") or {}
        start, end = _date_value(start_node), _date_value(end_node)
        current = bool(end_node.get("isCurrent")) if isinstance(end_node, dict) else False
        duration = _months(start, end, current)
        company = _text(item.get("workExperienceOrganization"))
        title = _text(item.get("workExperienceJobTitle"))
        if company: companies.append(company)
        if title: titles.append(title)
        experience.append({"company": company, "title": title, "designation": title, "employment_type": _text((item.get("workExperienceType") or {}).get("label")), "start_date": start, "end_date": end, "description": _text(item.get("workExperienceDescription"))})
        normalized_experience.append({"company": company, "job_title": title, "start_date": start, "end_date": end, "is_current": current, "duration_months": duration, "duration_display": f"{duration} months" if duration is not None else None})
    projects = _map_projects(data.get("project"), source_text)
    certifications = _unique([
        *[v for item in data.get("certification") or data.get("certifications") or [] if (v := _text(item.get("name") if isinstance(item, dict) else item))],
        *misclassified_certs,
    ])
    languages = _unique([v for item in data.get("language") or [] if (v := _text(item.get("name") if isinstance(item, dict) else item))])
    email_values = data.get("email") or []
    phone_values = data.get("phoneNumber") or []
    email = _text(email_values[0] if email_values else None)
    phone_item = phone_values[0] if phone_values else None
    phone = _text(phone_item.get("formattedNumber") or phone_item.get("rawText")) if isinstance(phone_item, dict) else _text(phone_item)
    if not phone and source_text:
        phone_match = re.search(r"(?:Phone|Mobile|Tel|Cell)?\s*[:\-]?\s*(\+?\d[\d\s\-]{8,}\d)", source_text, re.IGNORECASE)
        if phone_match:
            phone = phone_match.group(1).strip()
    location = data.get("location") if isinstance(data.get("location"), dict) else {}
    display = _text(location.get("formatted") or location.get("rawInput"))
    locations = [{"city": _text(location.get("city")), "region": _text(location.get("state")), "country": _text(location.get("country")), "country_code": _text(location.get("countryCode")), "display_name": display}] if display else []
    achievements = []
    if source_text:
        ach_match = re.search(
            r"(?:^|\n)\s*ACHIEVEMENTS\b[^\n]*\n(.*?)(?=\n\s*(?:EXPERIENCE|WORK\s+EXPERIENCE|EDUCATION|SKILLS|PROJECTS|CERTIFICATIONS|PUBLICATIONS|AWARDS|LANGUAGES|SUMMARY|PROFILE)\b|\Z)",
            source_text, re.DOTALL | re.IGNORECASE,
        )
        if ach_match:
            achievements = [line.strip() for line in ach_match.group(1).splitlines() if line.strip()]
    extracted = {"candidate_name": candidate_name, "email": email, "phone": phone, "designation": titles[0] if titles else None, "location": display, "skills": skills, "education": education, "experience": experience, "projects": projects, "certifications": certifications, "achievements": achievements, "companies": _unique(companies), "languages": languages, "confidence_scores": {}, "raw_metadata": {"provider": "affinda", "provider_document_id": provider_id}}
    normalized = {"skills": skills, "education": normalized_education, "companies": _unique(companies), "job_titles": _unique(titles), "experience": normalized_experience, "phone": phone, "email": email, "locations": locations, "languages": languages, "certifications": certifications, "achievements": achievements, "normalization_metadata": {"ruleset_version": RULESET_VERSION, "normalized_at": datetime.now(UTC).isoformat(), "changes": [], "warnings": [], "field_confidence": {}}, "ruleset_version": RULESET_VERSION}
    extracted["raw_metadata"]["affinda_normalized_profile"] = normalized
    logger.info(
        "[MAPPER] Affinda resume mapper completed",
        skills_count=len(skills),
        projects_count=len(projects),
        project_titles=[project.get("name") for project in projects],
        project_description_lengths=[len(project.get("description") or "") for project in projects],
        education_count=len(normalized_education),
        work_experience_count=len(normalized_experience),
    )
    return extracted, normalized


def map_affinda_jd(data: dict[str, Any], provider_id: str | None = None) -> dict[str, Any]:
    logger.info("[MAPPER] Affinda JD mapper started")
    skills = _unique([v for item in data.get("skills") or [] if (v := _skill_name(item))])
    education = _unique([v for item in data.get("educationAccreditation") or [] if (v := _text(item.get("name") if isinstance(item, dict) else item))])
    certifications = _unique([v for item in data.get("certifications") or [] if (v := _text(item.get("name") if isinstance(item, dict) else item))])
    years = data.get("yearsExperience")
    experience = [str(years)] if years not in (None, "", []) else []
    mapped = {"job_title": _text(data.get("jobTitle")), "domain": None, "skills": skills, "required_skills": skills, "preferred_skills": [], "responsibilities": [], "education": education, "education_disciplines": [], "experience": experience, "certifications": certifications, "keywords": skills, "confidence_scores": {}, "raw_metadata": {"provider": "affinda", "provider_document_id": provider_id}}
    logger.info(
        "[MAPPER] Affinda JD mapper completed",
        skills_count=len(skills),
        projects_count=0,
        project_titles=[],
        project_description_lengths=[],
        education_count=len(education),
        work_experience_count=len(experience),
    )
    return mapped
