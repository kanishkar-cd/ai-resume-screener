import re
from datetime import UTC, date, datetime
from typing import Any

# pyrefly: ignore [missing-import]
import structlog

from app.services.pipeline.canonical_dictionaries import (
    DEGREE_ALIASES, RULESET_VERSION, TITLE_ALIASES,
)
from app.services.pipeline.normalization_rules import (
    NormalizationAudit, canonicalize, clean_text, duration_between, format_duration,
    normalize_company, normalize_date, normalize_phone,
)

logger = structlog.get_logger(__name__)


def _clean_company_name(value: Any) -> str | None:
    val = _text(value)
    if not val:
        return None
    val = re.sub(r"^[•●▪*\- \t\r\n,.;:()]+", "", val).strip()
    val = re.sub(r"[,.;:()]+$", "", val).strip()
    if not val:
        return None
    if val.casefold() in {
        "present", "current", "now", "till date", "to date", "continuous",
        "experience", "work experience", "employment history", "professional experience",
        "internship", "internships", "projects", "technical projects", "education",
        "skills", "certifications", "responsibilities", "achievements", "summary",
    }:
        return None
    if re.match(r"^(?:(?:19|20)\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|summer|winter|spring|fall|\d+\s*months?|\d+\s*years?).*", val, flags=re.I):
        return None
    if len(val.split()) > 8:
        return None
    return val[:255]


def _clean_job_title(value: Any) -> str | None:
    val = _text(value)
    if not val:
        return None
    val = re.sub(r"^(?:role|designation|title|position)\s*[:\-–—]?\s*", "", val, flags=re.I).strip()
    val = re.sub(r"^[•●▪*\- \t\r\n,.;:()]+", "", val).strip()
    val = re.sub(r"[,.;:()]+$", "", val).strip()
    if not val:
        return None
    if val.casefold() in {
        "present", "current", "now", "till date", "to date", "continuous",
        "experience", "work experience", "employment history", "projects",
        "education", "skills", "certifications", "responsibilities", "achievements", "summary",
    }:
        return None
    if re.match(r"^(?:(?:19|20)\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d+\s*months?|\d+\s*years?).*", val, flags=re.I):
        return None
    if len(val.split()) > 8:
        return None
    return val[:255]


def _detect_employment_type(label: str | None, context: str | None) -> str:
    combined = f"{label or ''} {context or ''}".lower()
    if re.search(r"\b(?:intern|internship)\b", combined):
        return "Internship"
    if re.search(r"\b(?:apprentice|apprenticeship)\b", combined):
        return "Apprenticeship"
    if re.search(r"\b(?:trainee|graduate\s+trainee)\b", combined):
        return "Trainee"
    if re.search(r"\b(?:contract|contractor)\b", combined):
        return "Contract"
    if re.search(r"\b(?:freelance|freelancer)\b", combined):
        return "Freelance"
    if re.search(r"\b(?:volunteer|volunteering)\b", combined):
        return "Volunteer"
    if re.search(r"\bpart[\s-]time\b", combined):
        return "Part-time"
    return "Full-time"


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


def _normalize_technology_entries(explicit: Any) -> list[Any]:
    """Normalize raw technology/skill entries from Affinda into a flat list of entries."""
    if not explicit:
        return []
    if isinstance(explicit, str):
        parts = re.split(r"[,;|/]", explicit)
        return [part.strip() for part in parts if part.strip()]
    if isinstance(explicit, list):
        normalized: list[Any] = []
        for item in explicit:
            if isinstance(item, str):
                parts = re.split(r"[,;|/]", item)
                for part in parts:
                    if part.strip():
                        normalized.append(part.strip())
            elif isinstance(item, dict):
                name_val = item.get("name") if isinstance(item.get("name"), str) else None
                if name_val and re.search(r"[,;|/]", name_val):
                    parts = re.split(r"[,;|/]", name_val)
                    for part in parts:
                        if part.strip():
                            normalized.append({"name": part.strip()})
                else:
                    normalized.append(item)
        return normalized
    return []


def _map_projects(items: Any, source_text: str | None) -> list[dict[str, Any]]:
    raw_projects = [item for item in (items or []) if isinstance(item, dict)]
    source_descriptions = _source_project_descriptions(raw_projects, source_text)
    mapped: list[dict[str, Any]] = []
    for index, item in enumerate(raw_projects):
        explicit = item.get("technologies") or item.get("skills") or []
        explicit_entries = _normalize_technology_entries(explicit)
        raw_title = _text(item.get("projectTitle"))
        desc = source_descriptions.get(index) or _text(item.get("projectDescription"))
        project_name = raw_title.rstrip(" -–—") if raw_title else None
        if not project_name and desc:
            words = [w for w in re.split(r"\s+", desc.strip()) if w][:5]
            project_name = " ".join(words).title() if words else "Technical Project"
        elif not project_name:
            project_name = "Technical Project"

        mapped.append({
            "name": project_name,
            "description": desc,
            "technologies": _unique([
                value for entry in explicit_entries
                if (value := _skill_name(entry))
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

    has_explicit_titles = any(bool(_text(item.get("projectTitle"))) for item in raw_projects)

    is_dummy_mapped = bool(mapped) and all(
        (p.get("name") in (None, "", "Technical Project") and not p.get("description") and not p.get("technologies"))
        for p in mapped
    )

    if (not mapped or is_dummy_mapped or not has_explicit_titles) and source_text:
        from app.services.extractors.resume_extractor import ResumeExtractor
        from app.services.pipeline.extraction_pipeline import reconstruct_layout_text, segment_sections
        layout_text = reconstruct_layout_text(source_text)
        sections = segment_sections(layout_text)
        extracted_projs = ResumeExtractor._projects(sections.get("projects", ""))
        embedded_projs = (
            ResumeExtractor._extract_embedded_projects(sections.get("experience", ""))
            if sections.get("experience", "")
            else []
        )

        seen_names = {p["name"].casefold() for p in extracted_projs if p.get("name")}
        for ep in embedded_projs:
            if ep.get("name") and ep["name"].casefold() not in seen_names:
                seen_names.add(ep["name"].casefold())
                extracted_projs.append(ep)

        if extracted_projs:
            return extracted_projs

    if mapped and source_text and any(p.get("name") in (None, "", "Technical Project") or not p.get("description") for p in mapped):
        from app.services.extractors.resume_extractor import ResumeExtractor
        from app.services.pipeline.extraction_pipeline import reconstruct_layout_text, segment_sections
        layout_text = reconstruct_layout_text(source_text)
        sections = segment_sections(layout_text)
        fallback_projs = ResumeExtractor._projects(sections.get("projects", ""))
        if fallback_projs and len(fallback_projs) == len(mapped):
            for m_proj, f_proj in zip(mapped, fallback_projs):
                if m_proj.get("name") in (None, "", "Technical Project") and f_proj.get("name"):
                    m_proj["name"] = f_proj["name"]
                if not m_proj.get("description") and f_proj.get("description"):
                    m_proj["description"] = f_proj["description"]
                if not m_proj.get("technologies") and f_proj.get("technologies"):
                    m_proj["technologies"] = f_proj["technologies"]

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
    if isinstance(name, str):
        candidate_name = name.strip() or None
    elif isinstance(name, dict):
        candidate_name = " ".join(filter(None, [_text(name.get("firstName")), _text(name.get("middleName")), _text(name.get("familyName"))])) or _text(name.get("raw")) or None
    else:
        candidate_name = None
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
            if degree or institution or major:
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
        if not current and end and end.casefold() in {"present", "current", "now"}:
            current = True
            end = None
        duration = _months(start, end, current)
        
        raw_company = item.get("workExperienceOrganization")
        company = _text(raw_company.get("name") or raw_company.get("raw")) if isinstance(raw_company, dict) else _text(raw_company)
        company = _clean_company_name(company)
        
        raw_title = item.get("workExperienceJobTitle")
        title = _text(raw_title.get("name") or raw_title.get("raw")) if isinstance(raw_title, dict) else _text(raw_title)
        title = _clean_job_title(title)
        
        desc = _text(item.get("workExperienceDescription")) or ""
        raw_resp = item.get("workExperienceResponsibilities") or []
        responsibilities = [_text(r) for r in raw_resp if _text(r)] if isinstance(raw_resp, list) else []
        if not responsibilities and desc:
            responsibilities = [r.strip("•●▪*- \t") for r in desc.splitlines() if r.strip("•●▪*- \t")]
            
        emp_type_label = _text((item.get("workExperienceType") or {}).get("label")) if isinstance(item.get("workExperienceType"), dict) else _text(item.get("workExperienceType"))
        emp_type = _detect_employment_type(emp_type_label, f"{title or ''} {desc or ''}")
        
        loc_node = item.get("workExperienceLocation")
        loc_display = _text(loc_node.get("formatted") or loc_node.get("rawInput")) if isinstance(loc_node, dict) else _text(loc_node)

        if company:
            companies.append(company)
        if title:
            titles.append(title)
            
        if company or title or desc:
            experience.append({
                "company": company,
                "title": title,
                "designation": title,
                "employment_type": emp_type,
                "start_date": start,
                "end_date": end,
                "is_current": current,
                "duration": f"{duration} months" if duration is not None else None,
                "description": desc,
                "responsibilities": responsibilities,
                "location": loc_display,
            })
            normalized_experience.append({
                "company": company,
                "job_title": title,
                "employment_type": emp_type,
                "start_date": start,
                "end_date": end,
                "is_current": current,
                "duration_months": duration,
                "duration_display": f"{duration} months" if duration is not None else None,
                "description": desc,
                "responsibilities": responsibilities,
                "location": loc_display,
            })
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
    if phone:
        if re.search(r"[xX]{2,}", phone):
            phone = None
        else:
            digits = re.sub(r"\D", "", phone)
            if len(digits) < 8 or len(digits) > 15 or len(set(digits)) <= 2 or digits == "1234567890":
                phone = None
    if not phone and source_text:
        from app.services.extractors.resume_extractor import ResumeExtractor
        phone = ResumeExtractor._extract_phone(source_text)
    location = data.get("location") if isinstance(data.get("location"), dict) else {}
    display = _text(location.get("formatted") or location.get("rawInput"))
    locations = [{"city": _text(location.get("city")), "region": _text(location.get("state")), "country": _text(location.get("country")), "country_code": _text(location.get("countryCode")), "display_name": display}] if display else []
    achievements = []
    if source_text:
        from app.services.extractors.resume_extractor import ResumeExtractor
        try:
            local_ext = ResumeExtractor().extract(source_text)
            if not candidate_name and local_ext.get("candidate_name"):
                candidate_name = local_ext["candidate_name"]
            if not email and local_ext.get("email"):
                email = local_ext["email"]
            if not phone and local_ext.get("phone"):
                phone = local_ext["phone"]
            if not display and local_ext.get("location"):
                display = local_ext["location"]
                locations = [{"city": None, "region": None, "country": "India", "country_code": "IN", "display_name": display}]
            if not titles and local_ext.get("designation"):
                titles = [local_ext["designation"]]
            if not skills and local_ext.get("skills"):
                skills = _unique(local_ext["skills"])
            has_valid_education = any((item.get("degree") or item.get("institution")) for item in education)
            if (not education or not has_valid_education) and local_ext.get("education"):
                education = local_ext["education"]
                normalized_education = [{"degree": item.get("degree"), "field_of_study": item.get("field_of_study"), "institution": item.get("institution"), "graduation_date": item.get("year")} for item in education]
            has_valid_exp = any(bool(item.get("company") or item.get("title")) for item in experience)
            if (not experience or not has_valid_exp) and local_ext.get("experience"):
                fallback_exp = local_ext["experience"]
                experience = fallback_exp
                normalized_experience = []
                for item in fallback_exp:
                    s_date = item.get("start_date")
                    e_date = item.get("end_date")
                    dur = item.get("duration")
                    if not s_date and not e_date and dur:
                        parts = re.split(r"\s+(?:-|–|—|to)\s+", dur, maxsplit=1, flags=re.I)
                        s_date = parts[0] if parts else None
                        e_date = parts[1] if len(parts) == 2 else None
                    audit_dummy = NormalizationAudit()
                    norm_s, _ = normalize_date(s_date, "experience.start_date", audit_dummy)
                    norm_e, is_curr = normalize_date(e_date, "experience.end_date", audit_dummy)
                    if item.get("is_current") or (e_date and str(e_date).casefold() in {"present", "current", "now"}):
                        is_curr = True
                        norm_e = None
                    months = duration_between(norm_s, norm_e, is_curr)
                    comp = normalize_company(item.get("company"), audit_dummy)
                    raw_t = item.get("title") or item.get("designation")
                    t_canonical = canonicalize(raw_t, TITLE_ALIASES, "job_titles", audit_dummy) if raw_t else None
                    if comp:
                        companies.append(comp)
                    if t_canonical:
                        titles.append(t_canonical)
                    normalized_experience.append({
                        "company": comp,
                        "job_title": t_canonical,
                        "employment_type": item.get("employment_type") or "Full-time",
                        "start_date": norm_s,
                        "end_date": norm_e,
                        "is_current": is_curr,
                        "duration_months": months,
                        "duration_display": format_duration(months),
                        "description": item.get("description"),
                        "responsibilities": item.get("responsibilities") or [],
                        "location": item.get("location"),
                    })
            if not certifications and local_ext.get("certifications"):
                certifications = local_ext["certifications"]
            if local_ext.get("achievements"):
                achievements = local_ext["achievements"]
        except Exception as exc:
            logger.warning("[MAPPER] Local fallback extraction failed", error=str(exc))

    audit = NormalizationAudit()
    norm_phone = normalize_phone(phone, audit)
    norm_edu = [
        {
            "degree": canonicalize(item.get("degree"), DEGREE_ALIASES, "education.degree", audit),
            "field_of_study": clean_text(item.get("field_of_study")) if item.get("field_of_study") else None,
            "institution": clean_text(item.get("institution")) if item.get("institution") else None,
            "graduation_date": normalize_date(item.get("year") or item.get("graduation_date"), "education.graduation_date", audit)[0],
        }
        for item in (education or [])
    ]
    phone = phone[:32] if phone else None
    extracted = {"candidate_name": candidate_name, "email": email, "phone": phone, "designation": titles[0] if titles else None, "location": display, "skills": skills, "education": education, "experience": experience, "projects": projects, "certifications": certifications, "achievements": achievements, "companies": _unique(companies), "languages": languages, "confidence_scores": {}, "raw_metadata": {"provider": "affinda", "provider_document_id": provider_id}}
    normalized = {"skills": skills, "education": norm_edu, "companies": _unique(companies), "job_titles": _unique(titles), "experience": normalized_experience, "phone": norm_phone, "email": email, "locations": locations, "languages": languages, "certifications": certifications, "achievements": achievements, "normalization_metadata": {"ruleset_version": RULESET_VERSION, "normalized_at": datetime.now(UTC).isoformat(), "changes": [], "warnings": [], "field_confidence": {}}, "ruleset_version": RULESET_VERSION}
    extracted["raw_metadata"]["affinda_normalized_profile"] = normalized
    logger.info(
        "[MAPPER] Affinda resume mapper completed",
        skills_count=len(skills),
        projects_count=len(projects),
        project_titles=[(p.get("name") or "").encode("ascii", "ignore").decode("ascii") for p in projects],
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
