import re
from datetime import UTC, date, datetime
from typing import Any

# pyrefly: ignore [missing-import]
import structlog

from app.services.pipeline.canonical_dictionaries import (
    CERTIFICATION_ALIASES, DEGREE_ALIASES, LANGUAGE_ALIASES, LOCATION_ALIASES,
    RULESET_VERSION, SKILL_ALIASES, TITLE_ALIASES,
)
from app.services.pipeline.extraction_pipeline import DEGREES, DESIGNATIONS, SKILLS
from app.services.jd_extraction_service import SKILLS_VOCABULARY

logger = structlog.get_logger(__name__)


_SKILL_SUFFIX = re.compile(r"\s*\((?:programming language)\)\s*$", re.IGNORECASE)
_SKILL_ALIASES = {
    "cascading style sheets (css)": "CSS",
    "express.js (javascript library)": "Express.js",
    "git (version control system)": "Git",
    "html scripting": "HTML",
    "node.js (javascript library)": "Node.js",
    "object-oriented programming (oop)": "Object-Oriented Programming",
    "react.js (javascript library)": "React.js",
    "restful api": "REST API",
}

_KNOWN_TECHNICAL_SKILLS = frozenset({
    s.casefold() for s in (
        list(SKILL_ALIASES.keys()) +
        list(SKILL_ALIASES.values()) +
        list(_SKILL_ALIASES.keys()) +
        list(_SKILL_ALIASES.values()) +
        list(SKILLS) +
        list(SKILLS_VOCABULARY) +
        [
            "json", "sdlc", "debugging", "software testing", "testing",
            "postman", "playwright", "figma", "swagger", "git", "github",
            "gitlab", "object-oriented programming", "data structures and algorithms",
            "application programming interface", "c", "c++", "c#", ".net",
            "html", "css", "sql", "mysql", "postgresql", "mongodb", "redis",
            "react", "react.js", "node.js", "express.js", "fastapi", "spring boot",
            "aws", "docker", "agile", "ci/cd", "dsa", "oop",
        ]
    )
})

_NON_SKILL_PATTERNS = re.compile(
    r"^(?:"
    r"software engineering|computer science|engineering analysis|smartlist|branding|"
    r"academic support services|behavioral health|stand-up comedy|catia certification|"
    r"catia|management|communications|proxy statement|celestial navigation|results focused|"
    r"casting|rendering|retail management|analytics|academic support|behavioral|"
    r"information technology|business administration|"
    r"task management|performance analytics|parsing|information extraction|data processing|"
    r"problem solving|analytical thinking|quick learning|adaptability|soft skills|"
    r"communication|communication skills|teamwork|leadership|time management|"
    r"sales|customer analytics|business metrics|data extraction|retail sales"
    r")$",
    re.IGNORECASE,
)


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
    canonical = _SKILL_SUFFIX.sub("", value).strip()
    c_lower = canonical.casefold()

    source = source_text or ""
    # C vs C++ protection: If third-party parser maps C++ to "C" or "C (programming language)"
    if c_lower == "c" and source:
        has_cpp = bool(re.search(r"(?<![\w#+])C\+\+(?![\w#+])|\bcpp\b", source, re.IGNORECASE))
        has_standalone_c = bool(re.search(r"(?<![\w#+])C(?![\w#+])", source))
        if has_cpp and not has_standalone_c:
            canonical = "C++"
            c_lower = "c++"

    alias = _SKILL_ALIASES.get(c_lower) or SKILL_ALIASES.get(c_lower)
    if alias:
        return alias

    if c_lower == "application programming interface (api)":
        return "REST API" if re.search(r"\brest(?:ful)?\s+apis?\b", source, re.IGNORECASE) else "Application Programming Interface"
    if c_lower in ("data structures", "data structures and algorithms") and (
        not source or re.search(r"\b(?:dsa|data structures\s+and\s+algorithms)\b", source, re.IGNORECASE)
    ):
        return "Data Structures and Algorithms"

    # Check non-skill patterns first
    if _NON_SKILL_PATTERNS.match(c_lower):
        if source:
            skills_section_match = re.search(
                r"\bTECHNICAL SKILLS\b.*?(?=\b(?:EDUCATION|EXPERIENCE|PROJECTS|CERTIFICATIONS)\b|$)",
                source, re.IGNORECASE | re.DOTALL
            )
            if skills_section_match and re.search(rf"\b{re.escape(canonical)}\b", skills_section_match.group(0), re.IGNORECASE):
                return canonical
        return None

    # Known technical skill validation
    if c_lower in _KNOWN_TECHNICAL_SKILLS:
        return canonical

    # For unknown skills, ensure it is actually present in source_text (if available)
    if source and not re.search(rf"\b{re.escape(canonical)}\b", source, re.IGNORECASE):
        return None

    return canonical


def _map_projects(data: list[Any] | None, source_text: str | None = None) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    source_descriptions = []
    if source_text:
        project_matches = list(re.finditer(r"PROJECTS?\s*\n", source_text, re.IGNORECASE))
        if project_matches:
            project_block = source_text[project_matches[0].end():]
            end_match = re.search(r"\n\s*(?:EDUCATION|EXPERIENCE|CERTIFICATIONS|SKILLS)\b", project_block, re.IGNORECASE)
            if end_match:
                project_block = project_block[:end_match.start()]
            lines = [line.strip() for line in project_block.splitlines() if line.strip()]
            for line in lines:
                if line.startswith(("•", "-", "*", "1.", "2.", "3.")):
                    cleaned = line.lstrip("•-* 1234567890.").strip()
                    if len(cleaned) > 20:
                        source_descriptions.append(cleaned)
    for index, item in enumerate(data or []):
        if not isinstance(item, dict):
            continue
        name = _text(item.get("projectTitle") or item.get("name"))
        desc = _text(item.get("projectDescription") or item.get("description"))
        if not desc and index < len(source_descriptions):
            desc = source_descriptions[index]
        tech_items = item.get("technologies") or item.get("technology") or []
        tech_list = tech_items if isinstance(tech_items, list) else [tech_items]
        tech_text = " ".join([str(t) for t in tech_list]) + f" {desc or ''} {name or ''}"
        technologies = _unique([v for t in tech_list if (v := _skill_name(t, source_text))])
        if source_text:
            matched_skills = [s for s in SKILLS if re.search(rf"\b{re.escape(s)}\b", tech_text, re.IGNORECASE)]
            for ms in matched_skills:
                mapped_ms = _skill_name(ms, source_text)
                if mapped_ms and mapped_ms not in technologies:
                    technologies.append(mapped_ms)
        mapped.append({"name": name, "technologies": _unique(technologies), "description": desc})
    if not source_descriptions and len(mapped) > 1:
        descriptions = (mapped[0].get("description") or "").splitlines()
        descriptions = [value.strip() for value in descriptions if value.strip()]
        if len(descriptions) == len(mapped) and all(
            not project.get("description") for project in mapped[1:]
        ):
            for project, description in zip(mapped, descriptions, strict=True):
                project["description"] = description
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
    if source_text:
        deterministic_skills = [v for s in SKILLS if (v := _skill_name(s, source_text)) and re.search(rf"(?<![\w#+]){re.escape(s)}(?![\w#+])", source_text, re.IGNORECASE)]
        skills = _unique([*skills, *deterministic_skills])
    education, normalized_education = [], []
    certifications = _unique([v for item in data.get("certification") or data.get("certifications") or [] if (v := _text(item.get("name") if isinstance(item, dict) else item))])
    for item in data.get("education") or []:
        if not isinstance(item, dict):
            continue
        majors = item.get("educationMajor") or []
        major = _text(majors[0] if isinstance(majors, list) and majors else majors)
        degree = _text(item.get("educationAccreditation"))
        institution = _text(item.get("educationOrganization"))
        combined_text = f"{degree or ''} {institution or ''} {major or ''}".casefold()
        is_cert = any(
            kw in combined_text for kw in (
                "certification", "certificate", "fundamentals", "coursera", "udemy",
                "online certification", "springboard", "skillrack", "infosys", "exam", "bootcamp"
            )
        )
        has_academic_degree = any(
            deg_alias in (degree or "").casefold() for deg_alias in DEGREE_ALIASES
        ) or any(
            deg_term in combined_text for deg_term in (
                "b.tech", "btech", "b.e.", "be", "bachelor", "master", "m.tech", "mtech",
                "m.e.", "me", "b.sc", "bsc", "m.sc", "msc", "phd", "ph.d", "diploma", "degree"
            )
        )
        if is_cert and not has_academic_degree:
            cert_name = f"{degree or ''} - {institution or ''}".strip(" -") if degree and institution else (degree or institution or major)
            if cert_name:
                certifications.append(cert_name)
            continue
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
        desc = _text(item.get("workExperienceDescription"))
        if duration is None and desc:
            from app.services.pipeline.normalization_rules import parse_duration_months
            duration = parse_duration_months(desc)
        if duration is None and source_text:
            from app.services.pipeline.normalization_rules import parse_duration_months
            duration = parse_duration_months(source_text)
        company = _text(item.get("workExperienceOrganization"))
        title = _text(item.get("workExperienceJobTitle"))
        if company: companies.append(company)
        if title: titles.append(title)
        experience.append({"company": company, "title": title, "designation": title, "employment_type": _text((item.get("workExperienceType") or {}).get("label")), "start_date": start, "end_date": end, "description": desc, "duration_months": duration})
        normalized_experience.append({"company": company, "job_title": title, "start_date": start, "end_date": end, "is_current": current, "duration_months": duration, "duration_display": f"{duration} month{'s' if duration != 1 else ''}" if duration is not None else None})
    projects = _map_projects(data.get("project"), source_text)
    if not projects and source_text:
        from app.services.extractors.resume_extractor import ResumeExtractor
        deterministic_projects = ResumeExtractor._projects(source_text)
        if deterministic_projects:
            projects = []
            for dp in deterministic_projects:
                techs = _unique([v for t in (dp.get("technologies") or []) if (v := _skill_name(t, source_text))])
                if not techs:
                    combo = f"{dp.get('name') or ''} {dp.get('description') or ''}"
                    matched = [s for s in SKILLS if re.search(rf"\b{re.escape(s)}\b", combo, re.IGNORECASE)]
                    techs = _unique([v for s in matched if (v := _skill_name(s, source_text))])
                projects.append({
                    "name": dp.get("name"),
                    "description": dp.get("description"),
                    "technologies": techs,
                })
    certifications = _unique([v for item in data.get("certification") or data.get("certifications") or [] if (v := _text(item.get("name") if isinstance(item, dict) else item))])
    if source_text:
        from app.services.extractors.resume_extractor import ResumeExtractor
        from app.services.pipeline.extraction_pipeline import segment_sections
        sections = segment_sections(source_text)
        fallback_certs = ResumeExtractor._certifications(sections.get("certifications", ""))
        if fallback_certs:
            certifications = _unique([*certifications, *fallback_certs])
    languages = _unique([v for item in data.get("language") or [] if (v := _text(item.get("name") if isinstance(item, dict) else item))])
    email_values = data.get("email") or []
    phone_values = data.get("phoneNumber") or []
    email = _text(email_values[0] if email_values else None)
    phone_item = phone_values[0] if phone_values else None
    phone = _text(phone_item.get("formattedNumber") or phone_item.get("rawText")) if isinstance(phone_item, dict) else _text(phone_item)
    location = data.get("location") if isinstance(data.get("location"), dict) else {}
    display = _text(location.get("formatted") or location.get("rawInput"))
    locations = [{"city": _text(location.get("city")), "region": _text(location.get("state")), "country": _text(location.get("country")), "country_code": _text(location.get("countryCode")), "display_name": display}] if display else []
    extracted = {"candidate_name": candidate_name, "email": email, "phone": phone, "designation": titles[0] if titles else None, "location": display, "skills": skills, "education": education, "experience": experience, "projects": projects, "certifications": certifications, "companies": _unique(companies), "languages": languages, "confidence_scores": {}, "raw_metadata": {"provider": "affinda", "provider_document_id": provider_id}}
    normalized = {"skills": skills, "education": normalized_education, "companies": _unique(companies), "job_titles": _unique(titles), "experience": normalized_experience, "phone": phone, "email": email, "locations": locations, "languages": languages, "certifications": certifications, "normalization_metadata": {"ruleset_version": RULESET_VERSION, "normalized_at": datetime.now(UTC).isoformat(), "changes": [], "warnings": [], "field_confidence": {}}, "ruleset_version": RULESET_VERSION}
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


def map_affinda_jd(data: dict[str, Any], provider_id: str | None = None, source_text: str | None = None) -> dict[str, Any]:
    logger.info("[MAPPER] Affinda JD mapper started")
    skills = _unique([v for item in data.get("skills") or [] if (v := _skill_name(item))])
    education = _unique([v for item in data.get("educationAccreditation") or [] if (v := _text(item.get("name") if isinstance(item, dict) else item))])
    certifications = _unique([v for item in data.get("certifications") or [] if (v := _text(item.get("name") if isinstance(item, dict) else item))])
    years = data.get("yearsExperience")
    experience = [str(years)] if years not in (None, "", []) else []

    required_skills, preferred_skills = [], []
    if source_text:
        from app.services.jd_extraction_service import _split_sections, _canonical_skills
        sections = _split_sections(source_text)
        required_skills = _canonical_skills(sections.get("required_skills", ""))
        preferred_skills = _canonical_skills(sections.get("preferred_skills", ""))
        req_keys = {s.casefold() for s in required_skills}
        preferred_skills = [s for s in preferred_skills if s.casefold() not in req_keys]

    if not required_skills:
        required_skills = skills
    else:
        combined_keys = {s.casefold() for s in skills}
        for s in [*required_skills, *preferred_skills]:
            if s.casefold() not in combined_keys:
                skills.append(s)

    mapped = {
        "job_title": _text(data.get("jobTitle")),
        "domain": None,
        "skills": skills,
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "responsibilities": [],
        "education": education,
        "education_disciplines": [],
        "experience": experience,
        "certifications": certifications,
        "keywords": list(dict.fromkeys([*skills, *required_skills, *preferred_skills])),
        "confidence_scores": {},
        "raw_metadata": {"provider": "affinda", "provider_document_id": provider_id},
    }
    logger.info(
        "[MAPPER] Affinda JD mapper completed",
        skills_count=len(skills),
        required_skills_count=len(required_skills),
        preferred_skills_count=len(preferred_skills),
        education_count=len(education),
        work_experience_count=len(experience),
    )
    return mapped
