import re
from typing import Any

from app.services.pipeline.canonical_dictionaries import (
    DEGREE_ALIASES, LOCATION_ALIASES, TITLE_ALIASES,
)
from app.services.pipeline.extraction_pipeline import (
    DEGREES, DESIGNATIONS, EMAIL_PATTERN, LANGUAGES, PHONE_PATTERN, SKILLS,
    clean_unicode, content_lines, field_confidence, first_match, match_terms,
    reconstruct_layout_text, segment_sections,
)

YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
DURATION_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)?[\s.-]*(?:19|20)\d{2}\s*(?:-|–|—|to)\s*(?:Present|Current|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)?[\s.-]*(?:19|20)\d{2})\b|\b(?:\d+|[A-Z][a-z]+)\s+Months?\b",
    re.IGNORECASE,
)
DATE_RANGE_PATTERN = re.compile(
    r"\b\d{2}/\d{4}.*?\d{2}/\d{4}\b|\b\d{2}/\d{4}.*?\b(?:Present|Current)\b|\b(?:19|20)\d{2}.*?\b(?:Present|Current|(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
GRADE_PATTERN = re.compile(
    r"\b(?:CGPA|GPA|Percentage|Score)?\s*:?\s*(?:\b[0-9]\.[0-9]{1,2}(?:\s*CGPA)?(?:\s*/\s*[0-9]\.?[0-9]*|\s*/\s*10|\s*/\s*4)?|\b[1-9][0-9]\.?\d?\s*%)\b",
    re.IGNORECASE,
)
LOCATION_PATTERN = re.compile(r"(?im)^(?:location|address|city|country)\s*:\s*(.+)$")
INSTITUTION_PATTERN = re.compile(
    r"\b(?:University|College|Institute|School|Academy|Polytechnic|Campus)\b", re.I
)
COMPANY_PATTERN = re.compile(
    r"\b(?:Inc\.?|Corp\.?|Corporation|Ltd\.?|Limited|LLC|Technologies|Technology|Systems|Solutions|Labs|Services|Software|Consulting|Group|Centria)\b",
    re.I,
)
FIELD_PATTERN = re.compile(
    r"\b(?:Artificial Intelligence and Data Science|Artificial Intelligence|Data Science|Computer Science|Information Technology|Electrical Engineering|Electronics|Mechanical Engineering|Civil Engineering|Business Administration|Software Engineering)\b",
    re.I,
)


class ResumeExtractor:
    """Enterprise deterministic resume extractor using hierarchical section analysis."""

    def extract(self, raw_input_text: str) -> dict[str, Any]:
        text = reconstruct_layout_text(raw_input_text)
        sections = segment_sections(text)
        header_text = sections.get("header", "")
        header_lines = content_lines(header_text)

        candidate_name = self._candidate_name(header_lines)
        email = first_match(EMAIL_PATTERN, text)
        phone = self._extract_phone(text)
        location = self._location(header_text, text)
        skills = match_terms(text, SKILLS)
        education = self._education(sections.get("education", ""))
        experience = self._experience(sections.get("experience", ""))
        designation = self._designation(header_lines, sections, text, experience)
        projects = self._projects(sections.get("projects", ""))
        certifications = self._certifications(sections.get("certifications", ""))
        companies = list(dict.fromkeys(item["company"] for item in experience if item.get("company")))
        languages = match_terms(sections.get("languages", "") or text, LANGUAGES)

        values = {
            "candidate_name": candidate_name,
            "email": email,
            "phone": phone,
            "designation": designation,
            "location": location,
            "skills": skills,
            "education": education,
            "experience": experience,
            "projects": projects,
            "certifications": certifications,
            "companies": companies,
            "languages": languages,
        }

        quality = self._evaluate_quality(sections, values)

        return {
            **values,
            "confidence_scores": {
                "candidate_name": field_confidence(candidate_name, strong=True),
                "email": field_confidence(email, strong=True),
                "phone": field_confidence(phone, strong=True),
                "designation": field_confidence(designation),
                "location": field_confidence(location),
                "skills": field_confidence(skills),
                "education": field_confidence(education),
                "experience": field_confidence(experience),
                "projects": field_confidence(projects),
                "certifications": field_confidence(certifications),
                "companies": field_confidence(companies),
                "languages": field_confidence(languages),
            },
            "raw_metadata": {
                "method": "deterministic_hierarchical_rules",
                "sections": list(sections.keys()),
                **quality,
            },
        }

    @staticmethod
    def _candidate_name(lines: list[str]) -> str | None:
        for line in lines[:5]:
            if re.search(r"[@\d:/]|http", line):
                continue
            words = line.split()
            if 2 <= len(words) <= 4:
                clean = re.sub(r"[^\w\s.-]", "", line).strip()
                if clean and not match_terms(clean, DESIGNATIONS):
                    return clean[:255]
        return None

    @staticmethod
    def _extract_phone(text: str) -> str | None:
        cleaned = clean_unicode(text)
        text_no_email = EMAIL_PATTERN.sub("", cleaned)
        match = PHONE_PATTERN.search(text_no_email)
        if match:
            raw = match.group(0).strip(" ,.;:()")
            digits = re.sub(r"\D", "", raw)
            if len(digits) >= 10:
                return raw
        return None

    def _designation(
        self, header: list[str], sections: dict[str, str], text: str, experience: list[dict[str, Any]]
    ) -> str | None:
        # 1. Prefer title from experience section if available
        if experience and experience[0].get("title"):
            return experience[0]["title"]

        # 2. Check "Role :" pattern in text
        role_match = re.search(r"(?i)\brole\s*:\s*(.+)$", text, re.M)
        if role_match:
            role_text = role_match.group(1).strip()
            matched_role = match_terms(role_text, DESIGNATIONS)
            if matched_role:
                return matched_role[0]
            return role_text[:255]

        # 3. Search header
        matched_header = match_terms("\n".join(header[:6]), DESIGNATIONS)
        if matched_header:
            return matched_header[0]

        # 4. Search summary section
        summary = sections.get("summary", "")
        if summary:
            matched_summary = match_terms(summary, DESIGNATIONS)
            if matched_summary:
                return matched_summary[0]

        # 5. Fallback overall search
        matched_text = match_terms(text, DESIGNATIONS)
        if matched_text:
            return matched_text[0]

        return None

    @staticmethod
    def _location(header: str, text: str) -> str | None:
        # 1. Check Location: label
        loc_match = LOCATION_PATTERN.search(text)
        if loc_match:
            val = loc_match.group(1).strip()
            val = re.sub(r"\s+", " ", val)
            return val[:255]

        # 2. Check canonical location aliases (e.g. Coimbatore, Chennai, Bengaluru)
        text_lower = text.lower()
        for alias, loc_info in LOCATION_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", text_lower):
                return loc_info["display_name"]

        # 3. Check City, Country or City, State regex in top lines
        city_state_match = re.search(
            r"\b([A-Z][a-zA-Z\s]{2,20})\s*,\s*([A-Z][a-zA-Z\s]{2,20}|[A-Z]{2})\b",
            header,
        )
        if city_state_match:
            city, region = city_state_match.group(1).strip(), city_state_match.group(2).strip()
            if not match_terms(city, DESIGNATIONS) and not match_terms(region, DESIGNATIONS):
                return f"{city}, {region}"

        return None

    @staticmethod
    def _education(block: str) -> list[dict[str, str | None]]:
        if not block.strip():
            return []

        items: list[dict[str, str | None]] = []
        lines = content_lines(block)
        current: dict[str, str | None] | None = None

        for line in lines:
            degree_found = None
            for alias, canonical in DEGREE_ALIASES.items():
                if re.search(rf"\b{re.escape(alias)}\b", line, re.I):
                    degree_found = canonical
                    break
            if not degree_found:
                degrees = match_terms(line, DEGREES)
                if degrees:
                    deg = degrees[0]
                    degree_found = DEGREE_ALIASES.get(deg.lower(), deg)

            matched_degree = degree_found
            is_inst = bool(INSTITUTION_PATTERN.search(line))
            year_match = YEAR_PATTERN.search(line)
            field_match = FIELD_PATTERN.search(line)
            grade_match = GRADE_PATTERN.search(line)

            if matched_degree:
                if current and (current.get("degree") or current.get("institution")):
                    items.append(current)

                current = {
                    "degree": matched_degree,
                    "institution": line[:255] if is_inst else None,
                    "year": year_match.group(0) if year_match else None,
                    "field_of_study": field_match.group(0) if field_match else None,
                    "grade": grade_match.group(0) if grade_match else None,
                }
            elif current:
                if not current.get("institution") and (is_inst or (not grade_match and not year_match and not field_match and len(line.split()) <= 8)):
                    current["institution"] = line[:255]
                if not current.get("year") and year_match:
                    current["year"] = year_match.group(0)
                if not current.get("field_of_study") and field_match:
                    current["field_of_study"] = field_match.group(0)
                if not current.get("grade") and grade_match:
                    current["grade"] = grade_match.group(0)
            elif is_inst or year_match:
                current = {
                    "degree": None,
                    "institution": line[:255] if is_inst else None,
                    "year": year_match.group(0) if year_match else None,
                    "field_of_study": field_match.group(0) if field_match else None,
                    "grade": grade_match.group(0) if grade_match else None,
                }

        if current and (current.get("degree") or current.get("institution")):
            items.append(current)

        return items

    @staticmethod
    def _experience(block: str) -> list[dict[str, Any]]:
        lines = content_lines(block)
        if not lines:
            return []

        items: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for idx, line in enumerate(lines):
            duration = DURATION_PATTERN.search(line)
            date_range = DATE_RANGE_PATTERN.search(line)
            titles = match_terms(line, DESIGNATIONS)

            # Check "Role :" format
            role_match = re.search(r"(?i)\brole\s*:\s*(.+)$", line)
            role_title = role_match.group(1).strip() if role_match else None

            company_match = COMPANY_PATTERN.search(line)
            at_match = re.search(r"\bat\s+(.+?)(?:\s*[|,(]|$)", line, re.I)

            extracted_company = None
            if at_match:
                extracted_company = at_match.group(1).strip()
            elif company_match and not role_match:
                extracted_company = line.strip()
            elif idx > 0 and (role_match or titles) and not company_match:
                prev_line = lines[idx - 1].strip()
                if not match_terms(prev_line, DESIGNATIONS) and len(prev_line.split()) <= 6:
                    extracted_company = prev_line

            title_val = role_title or (titles[0] if titles else None)
            dur_val = date_range.group(0) if date_range else (duration.group(0) if duration else None)

            # Check if line signals a new entry
            is_new_entry = False
            if current and current.get("company") and current.get("title") and (title_val or extracted_company):
                is_new_entry = True

            if is_new_entry:
                items.append(current)
                current = {
                    "company": extracted_company[:255] if extracted_company else None,
                    "title": title_val,
                    "duration": dur_val,
                    "responsibilities": [],
                }
            elif current and not current.get("title") and title_val:
                current["title"] = title_val
                if extracted_company and not current.get("company"):
                    current["company"] = extracted_company
                if dur_val and not current.get("duration"):
                    current["duration"] = dur_val
            elif current and not current.get("company") and extracted_company:
                current["company"] = extracted_company
                if dur_val:
                    current["duration"] = dur_val
            elif current and dur_val and not (title_val or extracted_company):
                current["duration"] = dur_val
            elif title_val or extracted_company or dur_val:
                if current and (current.get("company") or current.get("title")):
                    items.append(current)

                current = {
                    "company": extracted_company[:255] if extracted_company else None,
                    "title": title_val,
                    "duration": dur_val,
                    "responsibilities": [],
                }
            elif current:
                current["responsibilities"].append(line)

        if current and (current.get("company") or current.get("title")):
            items.append(current)

        return items

    @staticmethod
    def _projects(block: str) -> list[dict[str, Any]]:
        if not block.strip():
            return []

        projects: list[dict[str, Any]] = []
        current_project: dict[str, Any] | None = None

        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            is_bullet = raw_line.lstrip().startswith(("-", "*", "•", "▪"))
            is_proj_header = re.match(r"(?i)^(?:project\s*:|\d+[\.\)]\s*project|project\b)", line)
            is_header = is_proj_header or (not is_bullet and (":" in line or "(" in line or current_project is None))

            clean_text = re.sub(r"^[\s•●▪*–—-]+", "", line).strip()
            clean_text = re.sub(r"(?i)^project\s*:\s*", "", clean_text).strip()

            if is_header and not (current_project and len(current_project["description"]) == 0):
                if current_project:
                    projects.append(current_project)

                name, separator, desc = clean_text.partition(":")
                title_name = name.strip() if separator else clean_text.strip()
                desc_text = desc.strip() if separator else ""

                current_project = {
                    "name": title_name[:255],
                    "description": desc_text,
                    "technologies": match_terms(line, SKILLS),
                }
            elif current_project:
                if current_project["description"]:
                    current_project["description"] += " " + clean_text
                else:
                    current_project["description"] = clean_text

                techs = match_terms(clean_text, SKILLS)
                for tech in techs:
                    if tech not in current_project["technologies"]:
                        current_project["technologies"].append(tech)

        if current_project:
            projects.append(current_project)

        return projects

    @staticmethod
    def _certifications(block: str) -> list[str]:
        if not block.strip():
            return []

        cert_keywords = (
            "certified", "certificate", "certification", "aws", "pmp", "cka",
            "azure", "scrum", "oracle", "google", "coursera", "udemy", "ccna",
        )
        certs = []
        for line in content_lines(block):
            line_lower = line.lower()
            if any(term in line_lower for term in ("internship", "project", "publication", "award")):
                continue
            if any(kw in line_lower for kw in cert_keywords):
                certs.append(line[:255])
        return certs

    @staticmethod
    def _evaluate_quality(sections: dict[str, str], values: dict[str, Any]) -> dict[str, Any]:
        known_sections = {"header", "skills", "experience", "education", "projects", "certifications"}
        detected_known = [s for s in sections if s in known_sections]
        section_detection_score = round(len(detected_known) / len(known_sections), 2)

        extracted_counts = 0
        total_fields = len(values)
        warnings: list[str] = []

        for key, val in values.items():
            if val:
                extracted_counts += 1
            else:
                warnings.append(f"Field '{key}' could not be extracted.")

        entity_extraction_score = round(extracted_counts / total_fields, 2)
        overall_quality_score = round((section_detection_score * 0.4) + (entity_extraction_score * 0.6), 2)

        return {
            "section_detection_score": section_detection_score,
            "entity_extraction_score": entity_extraction_score,
            "overall_quality_score": overall_quality_score,
            "warnings": warnings,
        }
