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
        if experience and experience[0].get("designation"):
            return experience[0]["designation"]
        if experience and experience[0].get("title"):
            return experience[0]["title"]

        role_match = re.search(r"(?i)\brole\s*:\s*(.+)$", text, re.M)
        if role_match:
            role_text = role_match.group(1).strip()
            matched_role = match_terms(role_text, DESIGNATIONS)
            if matched_role:
                return matched_role[0]
            return role_text[:255]

        matched_header = match_terms("\n".join(header[:6]), DESIGNATIONS)
        if matched_header:
            return matched_header[0]

        summary = sections.get("summary", "")
        if summary:
            matched_summary = match_terms(summary, DESIGNATIONS)
            if matched_summary:
                return matched_summary[0]

        matched_text = match_terms(text, DESIGNATIONS)
        if matched_text:
            return matched_text[0]

        return None

    @staticmethod
    def _location(header: str, text: str) -> str | None:
        loc_match = LOCATION_PATTERN.search(text)
        if loc_match:
            val = loc_match.group(1).strip()
            val = re.sub(r"\s+", " ", val)
            return val[:255]

        text_lower = text.lower()
        for alias, loc_info in LOCATION_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", text_lower):
                return loc_info["display_name"]

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

    @classmethod
    def _experience(cls, block: str) -> list[dict[str, Any]]:
        lines = content_lines(block)
        if not lines:
            return []

        items: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for idx, line in enumerate(lines):
            prev_line = lines[idx - 1] if idx > 0 else None

            duration = DURATION_PATTERN.search(line)
            date_range = DATE_RANGE_PATTERN.search(line)
            titles = match_terms(line, DESIGNATIONS)

            role_match = re.search(r"(?i)\brole\s*:\s*(.+)$", line)
            role_title = role_match.group(1).strip() if role_match else None

            extracted_company = cls._extract_company_from_line(line, prev_line, role_match)

            title_val = role_title or (titles[0] if titles else None)

            # Text duration (e.g. "Three Months Internship") vs date-range string
            text_dur_val: str | None = duration.group(0) if duration else None
            date_dur_val: str | None = date_range.group(0) if date_range else None
            # Prefer human-readable text duration; fall back to date string
            dur_val: str | None = text_dur_val or date_dur_val

            start_date, end_date = None, None
            if date_range:
                raw_range = date_range.group(0)
                parts = re.split(r"\s*(?:-|–|—|to)\s*", raw_range, flags=re.I)
                if len(parts) == 2:
                    start_date, end_date = parts[0].strip(), parts[1].strip()

            is_intern = bool(re.search(r"\bintern(?:ship)?\b", line, re.I)) or (role_title and "intern" in role_title.lower())

            is_new_entry = False
            if current and current.get("company") and (current.get("designation") or current.get("title")) and (title_val or extracted_company):
                is_new_entry = True

            if is_new_entry:
                if current.get("description_lines"):
                    current["description"] = " ".join(current["description_lines"])
                items.append(cls._format_experience_item(current))
                current = cls._new_experience_item(
                    company=extracted_company,
                    designation=title_val,
                    employment_type="Internship" if is_intern else "Full-time",
                    start_date=start_date,
                    end_date=end_date,
                    duration=dur_val,
                )
            elif current:
                if not current.get("designation") and title_val:
                    current["designation"] = title_val
                    current["title"] = title_val
                    if is_intern:
                        current["employment_type"] = "Internship"
                if not current.get("company") and extracted_company:
                    current["company"] = extracted_company
                # Duration: set text duration; always update start/end from date_range
                if text_dur_val and not current.get("duration"):
                    current["duration"] = text_dur_val
                if date_dur_val:
                    # If only date range seen so far (no text), store it as duration too
                    if not current.get("duration"):
                        current["duration"] = date_dur_val
                    # Extract start/end regardless of whether duration is already set
                    if start_date and not current.get("start_date"):
                        current["start_date"] = start_date
                    if end_date and not current.get("end_date"):
                        current["end_date"] = end_date

                if not (title_val or extracted_company or dur_val):
                    # Filter OCR noise: isolated fragments ≤8 chars that are
                    # not alphabetic words (e.g. "Coimba", "Delh", "Mumba")
                    if len(line) <= 8 and re.match(r'^[A-Z][a-z]+$', line) and not re.search(r'\s', line):
                        continue  # skip city fragment noise
                    current["description_lines"].append(line)
                    current["responsibilities"].append(line)
            elif title_val or extracted_company or dur_val or is_intern:
                current = cls._new_experience_item(
                    company=extracted_company,
                    designation=title_val,
                    employment_type="Internship" if is_intern else "Full-time",
                    start_date=start_date,
                    end_date=end_date,
                    duration=dur_val,
                )

        if current:
            if current.get("description_lines"):
                current["description"] = " ".join(current["description_lines"])
            elif not current.get("description"):
                current["description"] = " ".join(filter(None, [current.get("company"), current.get("designation"), current.get("duration")]))
            items.append(cls._format_experience_item(current))

        return items

    @staticmethod
    def _new_experience_item(
        company: str | None,
        designation: str | None,
        employment_type: str,
        start_date: str | None,
        end_date: str | None,
        duration: str | None,
    ) -> dict[str, Any]:
        return {
            "company": company[:255] if company else None,
            "designation": designation,
            "title": designation,
            "employment_type": employment_type,
            "start_date": start_date,
            "end_date": end_date,
            "duration": duration,
            "description": "",
            "description_lines": [],
            "responsibilities": [],
        }

    @staticmethod
    def _format_experience_item(item: dict[str, Any]) -> dict[str, Any]:
        res = dict(item)
        res.pop("description_lines", None)
        return res

    @staticmethod
    def _extract_company_from_line(line: str, prev_line: str | None, role_match: re.Match | None) -> str | None:
        cleaned = re.sub(
            r",\s*(?:Coimbatore|Chennai|Bengaluru|Mumbai|Delhi|Hyderabad|London|San Francisco|CA|UK|India|[A-Z][a-zA-Z\s]{2,15})$",
            "",
            line,
            flags=re.I,
        ).strip()

        at_match = re.search(r"\bat\s+(.+?)(?:\s*[|,(]|$)", line, re.I)
        if at_match:
            comp = at_match.group(1).strip()
            if not match_terms(comp, DESIGNATIONS) and not DURATION_PATTERN.search(comp):
                return comp[:255]

        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            for p in parts:
                if (
                    not match_terms(p, DESIGNATIONS)
                    and not DURATION_PATTERN.search(p)
                    and not DATE_RANGE_PATTERN.search(p)
                    and len(p.split()) <= 6
                ):
                    return p[:255]

        if " - " in line or " – " in line or " — " in line:
            parts = [p.strip() for p in re.split(r"\s*[-–—]\s*", line)]
            for p in parts:
                if (
                    not match_terms(p, DESIGNATIONS)
                    and not DURATION_PATTERN.search(p)
                    and not DATE_RANGE_PATTERN.search(p)
                    and not YEAR_PATTERN.search(p)
                    and len(p.split()) <= 6
                ):
                    return p[:255]

        if (role_match or "role :" in line.lower() or "role:" in line.lower()) and prev_line:
            prev_clean = re.sub(
                r",\s*(?:Coimbatore|Chennai|Bengaluru|Mumbai|Delhi|Hyderabad|London|San Francisco|CA|UK|India|[A-Z][a-zA-Z\s]{2,15})$",
                "",
                prev_line,
                flags=re.I,
            ).strip()
            if not match_terms(prev_clean, DESIGNATIONS) and len(prev_clean.split()) <= 6:
                return prev_clean[:255]

        company_match = COMPANY_PATTERN.search(cleaned)
        if company_match and not role_match:
            return cleaned[:255]

        if prev_line and (role_match or "role" in line.lower()):
            prev_clean = re.sub(
                r",\s*(?:Coimbatore|Chennai|Bengaluru|Mumbai|Delhi|Hyderabad|London|San Francisco|CA|UK|India|[A-Z][a-zA-Z\s]{2,15})$",
                "",
                prev_line,
                flags=re.I,
            ).strip()
            if not match_terms(prev_clean, DESIGNATIONS) and len(prev_clean.split()) <= 6:
                return prev_clean[:255]

        return None

    @staticmethod
    def _projects(block: str) -> list[dict[str, Any]]:
        if not block.strip():
            return []

        projects: list[dict[str, Any]] = []
        current_project: dict[str, Any] | None = None
        lines = content_lines(block)

        # Heading pattern matching "Project:", "PROJECT:", "• Project:", "● Project:", "○ Project:", "1. Project:" etc.
        proj_heading_re = re.compile(
            r"^(?:[•●○▪*–—\d\.\)\s]*)(?:project\s*:|\d+[\.\)]\s*project|project\b)",
            re.IGNORECASE,
        )

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            is_proj_title = bool(proj_heading_re.match(line_str))
            
            # Clean heading prefixes
            clean_text = proj_heading_re.sub("", line_str).strip()
            clean_text = re.sub(r"^[::•●○▪*–—\s-]+", "", clean_text).strip()

            if is_proj_title:
                if current_project:
                    projects.append(current_project)

                title_source = clean_text if clean_text else line_str
                title_name = re.sub(r"\s*\([^)]*\)\s*$", "", title_source).strip() or title_source
                title_name = title_name.rstrip(" :").strip()

                current_project = {
                    "name": title_name[:255],
                    "description": title_source,
                    "technologies": match_terms(line_str, SKILLS),
                }
            elif current_project is None:
                title_name = re.sub(r"\s*\([^)]*\)\s*$", "", clean_text).strip() or clean_text
                title_name = title_name.rstrip(" :").strip()
                current_project = {
                    "name": title_name[:255],
                    "description": clean_text,
                    "technologies": match_terms(clean_text, SKILLS),
                }
            else:
                # If line starts with bullet heading that indicates another project title without "Project:" keyword
                is_bullet_heading = bool(re.match(r"^[•●○▪*]\s*[A-Z]", line_str)) and len(line_str.split()) <= 6 and ":" in line_str
                if is_bullet_heading and not match_terms(clean_text, SKILLS):
                    projects.append(current_project)
                    title_name = clean_text.rstrip(" :").strip()
                    current_project = {
                        "name": title_name[:255],
                        "description": clean_text,
                        "technologies": match_terms(clean_text, SKILLS),
                    }
                    continue

                current_project["description"] += (" " if current_project["description"] else "") + clean_text
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

        ignore_terms = (
            "internship", "project", "education", "experience", "work history",
            "employment", "trophies", "hobbies", "declaration",
        )
        lines = content_lines(block)
        raw_certs: list[str] = []

        for line in lines:
            line_lower = line.lower()
            if any(term in line_lower for term in ignore_terms):
                continue
            # Skip standalone OCR noise words that are not valid certifications
            # e.g. a line that is only "Badge", "badge", "Badges", or similar
            if re.fullmatch(r"badges?", line.strip(), re.I):
                continue
            # Strip leading bullets/numbers
            clean = re.sub(r"^[\s•●▪*–—\d\.\)]+", "", line).strip()
            if not clean or len(clean) < 2:
                continue
            # Remove OCR garbage: trailing counts like ",3" or " 3" but NOT 3-digit numbers (cert codes)
            clean = re.sub(r",\s*\d{1,2}\s*$", "", clean).strip()   # trailing ,N or ,NN  (e.g. "badges,3")
            clean = re.sub(r"\s+\d+\s*badges?\b.*$", "", clean, flags=re.I).strip()
            clean = re.sub(r"\s*-?\s*\d+\s*badges?\b.*$", "", clean, flags=re.I).strip()
            # After badge removal, if the remaining text is empty or just a noise word, skip it
            if not clean or re.fullmatch(r"badges?", clean, re.I):
                continue
            # Normalize DP900-N (OCR: missing hyphen) → DP-900. Do NOT touch already-correct DP-900.
            clean = re.sub(r"\bDP\s*900(?:-\s*\d+)?\b", "DP-900", clean, flags=re.I)

            # Add missing space before opening paren: "System(IIRS)" → "System (IIRS)"
            clean = re.sub(r"([A-Za-z])\(", r"\1 (", clean)
            # Remove trailing " - Training" / "- Training" suffix that leaks from AWS cert OCR
            clean = re.sub(r"\s*-\s*Training\s*$", "", clean, flags=re.I).strip()
            # Replace 'Graduate' with nothing when it precedes a hyphen (AWS Academy Graduate- → AWS Academy)
            clean = re.sub(r"\s*Graduate-\s*$", "", clean, flags=re.I).strip()
            if clean and len(clean) >= 2:
                raw_certs.append(clean)

        if not raw_certs:
            return []

        cert_prefixes = (
            "aws", "azure", "google", "oracle", "mongodb", "hackathon",
            "certified", "certificate", "coursera", "udemy", "ccna", "pmp",
        )

        merged_certs: list[str] = []
        i = 0
        while i < len(raw_certs):
            current = raw_certs[i]
            merged = False

            if i + 1 < len(raw_certs):
                next_line = raw_certs[i + 1]
                next_lower = next_line.lower()

                is_next_standalone = any(next_lower.startswith(prefix) for prefix in cert_prefixes)

                is_wrapped = (
                    # Current ends with hyphen (continuation)
                    current.endswith("-")
                    # Next starts with opening paren — e.g. "(IIRS)" continuation
                    or next_line.startswith("(")
                    # Current ends with a joining word
                    or re.search(r"\b(?:of|and|in|for|the|with|geographical|academy)\b$", current, re.I)
                    # Next starts with a continuation word
                    or re.search(
                        r"^(?:system|systems|information|foundations|solutions|architect|associate|"
                        r"engineer|developer|management|field|cloud|graduate|foundations)\b",
                        next_line, re.I,
                    )
                )

                if is_wrapped and not is_next_standalone:
                    # Merge: strip trailing hyphen before joining
                    base = current.rstrip("-").strip()
                    current = f"{base} {next_line}".strip()
                    i += 1
                    merged = True

            # Final cleanup on merged line
            current = re.sub(r"\s*-\s*Training\s*$", "", current, flags=re.I).strip()
            # AWS Academy Graduate Cloud Foundations → AWS Academy Cloud Foundations
            current = re.sub(r"\bGraduate\s+", "", current, flags=re.I).strip()
            merged_certs.append(current[:255])
            i += 1

        return merged_certs

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
