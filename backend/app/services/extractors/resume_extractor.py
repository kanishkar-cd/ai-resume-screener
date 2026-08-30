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
    r"\b(?:(?:CGPA|GPA|Percentage|Score)\s*[:=]?\s*\d+(?:\.\d+)?(?:\s*\/\s*\d+(?:\.\d+)?)?|\d+(?:\.\d+)?\s*(?:CGPA|GPA|\/\s*\d+(?:\.\d+)?|\%)|\bPASS\b)",
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

        candidate_name = self._candidate_name(header_lines) or self._candidate_name(content_lines(text))
        email = self._extract_email(text)
        phone = self._extract_phone(text)

        location = self._location(header_text, text)
        skills = self._skills(sections.get("skills", ""), text)
        education = self._education(sections.get("education", ""))
        experience = self._experience(sections.get("experience", ""))
        designation = self._designation(header_lines, sections, text, experience)
        projects = self._projects(sections.get("projects", ""))
        if not projects and sections.get("experience", ""):
            projects = self._extract_embedded_projects(sections.get("experience", ""))
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
    def _extract_email(text: str) -> str | None:
        matched = first_match(EMAIL_PATTERN, text)
        if not matched:
            return None
        # Clean merged OCR text (e.g. "abc@gmail.comwww.linkedin.com" -> "abc@gmail.com")
        cleaned_email = re.sub(r"(?i)(?:www\.|https?://|linkedin\.com|github\.com).*", "", matched).strip(" ,.;:()")
        return cleaned_email or matched

    GENERIC_DOCUMENT_TITLES = {
        "resume",
        "resumes",
        "curriculum vitae",
        "curriculum-vitae",
        "curriculum_vitae",
        "curriculum",
        "vitae",
        "cv",
        "biodata",
        "bio-data",
        "bio_data",
        "bio",
        "data",
        "profile",
        "applicant",
        "candidate",
        "candidate profile",
    }

    @classmethod
    def _candidate_name(cls, lines: list[str]) -> str | None:
        from app.services.pipeline.extraction_pipeline import SECTION_ALIASES
        all_headings = {alias for aliases in SECTION_ALIASES.values() for alias in aliases}
        for line in lines[:8]:
            line_no_contact = re.sub(r"\S+@\S+|\+?\d[\d\s\-]{8,}\d|https?://\S+", "", line).strip()
            if not line_no_contact:
                continue
            parts = [p.strip() for p in re.split(r"[|\-–—]", line_no_contact) if p.strip()]
            candidate_part = parts[0] if parts else line_no_contact
            clean_no_desig = re.sub(
                r"\b(?:Senior|Junior|Lead|Principal|Staff|Associate|Intern)?\s*(?:SysOps|SecOps|DevOps|PMO|QA|SRE|Software|Data|Backend|Frontend|Full\s*Stack|Cloud|Infrastructure|Systems?)\s*(?:Engineer|Analyst|Developer|Architect|Lead|Manager)?\b.*$",
                "", candidate_part, flags=re.I
            ).strip()
            target = clean_no_desig if clean_no_desig else candidate_part
            words = target.split()
            if 1 <= len(words) <= 5:
                clean = re.sub(r"[^\w\s.-]", "", target).strip()
                normalized = clean.casefold()
                if not clean or len(clean) < 3 or normalized in all_headings or normalized in cls.GENERIC_DOCUMENT_TITLES or match_terms(clean, DESIGNATIONS) or normalized in {"senior", "junior", "lead", "principal", "staff", "associate", "intern"}:
                    continue
                return clean.title()[:255]
        return None

    @staticmethod
    def _extract_phone(text: str) -> str | None:
        if not text:
            return None
        cleaned = clean_unicode(text)
        text_no_email = EMAIL_PATTERN.sub("", cleaned)
        
        # 1. First priority: explicit phone label (e.g. Phone: +91 9344081155, Mobile: 9159725713)
        label_match = re.search(r"(?i)\b(?:Phone|Mobile|Tel|Cell|Contact)\s*[:\-–—]?\s*(\+?[\d\s\-().]{8,20}\d)", text_no_email)
        if label_match:
            raw = label_match.group(1).strip(" ,.;:()")
            if not re.search(r"[xX]{2,}", raw):
                digits = re.sub(r"\D", "", raw)
                if 10 <= len(digits) <= 15 and len(set(digits)) > 2 and digits != "1234567890":
                    return raw

        # 2. Second priority: E.164 international phone number with '+' (e.g. +91 9344081155, +919361280237, +1 (555) 123-4567)
        intl_match = re.search(r"\+\d{1,3}[\s\-.]?\(?\d{1,5}\)?[\s\-.]?\d{3,5}[\s\-.]?\d{3,5}\b", text_no_email)
        if intl_match:
            raw = intl_match.group(0).strip(" ,.;:()")
            if not re.search(r"[xX]{2,}", raw):
                digits = re.sub(r"\D", "", raw)
                if 10 <= len(digits) <= 15 and len(set(digits)) > 2 and digits != "1234567890":
                    return raw

        # 3. Third priority: standard 10-digit Indian mobile number starting with 6-9 in header/contact lines
        header_lines = text_no_email.splitlines()[:12]
        header_text = "\n".join(header_lines)
        match = re.search(r"\b([6-9]\d{4}[\s.-]?\d{5}|[6-9]\d{9})\b", header_text)
        if match:
            raw = match.group(0).strip(" ,.;:()")
            digits = re.sub(r"\D", "", raw)
            if len(digits) == 10 and len(set(digits)) > 2 and digits != "1234567890":
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
            return role_match.group(1).strip()[:255]

        for line in header:
            roles = match_terms(line, DESIGNATIONS)
            if roles:
                return roles[0][:255]

        for block_name in ("summary", "experience"):
            block_roles = match_terms(sections.get(block_name, ""), DESIGNATIONS)
            if block_roles:
                return block_roles[0][:255]

        return None

    def _location(self, header: str, full_text: str) -> str | None:
        loc_match = re.search(r"(?im)^(?:location|address|city|country)\s*[:\-–—]?\s*(.+)$", full_text)
        if loc_match:
            val = loc_match.group(1).strip()
            val = re.sub(r"\s+", " ", val)
            return val[:255]

        header_lines = [l.strip() for l in header.splitlines() if l.strip()]
        for line in header_lines:
            matched = first_match(LOCATION_PATTERN, line)
            if matched:
                return matched.strip()[:255]
            for loc in LOCATION_ALIASES.values():
                name = loc["display_name"]
                if name.lower() in line.lower():
                    return name

        city_state_match = re.search(
            r"\b([A-Z][a-zA-Z\s]{2,20})\s*,\s*([A-Z][a-zA-Z\s]{2,20}|[A-Z]{2})\b",
            header,
        )
        if city_state_match:
            city, region = city_state_match.group(1).strip(), city_state_match.group(2).strip()
            if not match_terms(city, DESIGNATIONS) and not match_terms(region, DESIGNATIONS):
                return f"{city}, {region}"

        for loc in LOCATION_ALIASES.values():
            name = loc["display_name"]
            if name.lower() in header.lower():
                return name

        for line in header_lines:
            line_no_contact = re.sub(r"\S+@\S+|\+?\d[\d\s\-]{8,}\d|https?://\S+", "", line).strip(" ,|•–—")
            if line_no_contact and len(line_no_contact.split()) <= 4:
                for part in re.split(r"[,|/•–—]", line_no_contact):
                    part_clean = part.strip()
                    if part_clean.casefold() in LOCATION_ALIASES:
                        return LOCATION_ALIASES[part_clean.casefold()]["display_name"]

        return None

    DEGREE_EXTRACTION_PATTERNS = (
        (r"\b(?:B\.Tech|BTech|Bachelor\s+of\s+Technology)\b", "Bachelor of Technology"),
        (r"\b(?:B\.E\.|B\.E|BE)\b(?:\.|\b|[A-Z])", "Bachelor of Engineering"),
        (r"\b(?:M\.E\.|M\.E|ME)\b(?:\.|\b|[A-Z])", "Master of Engineering"),
        (r"\b(?:M\.Tech|MTech|Master\s+of\s+Technology)\b", "Master of Technology"),
        (r"\b(?:B\.Sc|BSc|B\.S\.|B\.S|BS|Bachelor\s+of\s+Science)\b", "Bachelor of Science"),
        (r"\b(?:M\.Sc|MSc|M\.S\.|M\.S|MS|Master\s+of\s+Science)\b", "Master of Science"),
        (r"\b(?:BCA|Bachelor\s+of\s+Computer\s+Applications)\b", "Bachelor of Computer Applications"),
        (r"\b(?:MCA|Master\s+of\s+Computer\s+Applications)\b", "Master of Computer Applications"),
        (r"\b(?:B\.A\.|BA|Bachelor\s+of\s+Arts)\b", "Bachelor of Arts"),
        (r"\b(?:B\.Com|BCom|Bachelor\s+of\s+Commerce)\b", "Bachelor of Commerce"),
        (r"\b(?:MBA|Master\s+of\s+Business\s+Administration)\b", "Master of Business Administration"),
        (r"\b(?:Ph\.D|PhD|Doctor\s+of\s+Philosophy|Doctorate)\b", "Doctor of Philosophy"),
        (r"\b(?:Diploma)\b", "Diploma"),
        (r"\b(?:HSC|Higher\s+Secondary\s+Education|Higher\s+Secondary\s+Certificate|Class\s+XII|Class\s+12|12th(?:\s+Grade|\s+Standard)?|Intermediate|\+2|Plus\s+Two|Pre-University|PUC)\b|\bHigher\s+Secondary\b(?!\s+School)", "Higher Secondary (12th)"),
        (r"\b(?:SSLC|Secondary\s+School\s+Leaving\s+Certificate|Secondary\s+School\s+Certificate|Class\s+X|Class\s+10|10th(?:\s+Grade|\s+Standard)?|Matriculation)\b|\b10th\b", "Secondary School (10th)"),
    )

    FIELD_EXTRACTION_PATTERNS = (
        (r"\b(?:Artificial\s+Intelligence\s+(?:and|&)\s+Data\s+Science|AI\s*(?:&|and)\s*DS)\b", "Artificial Intelligence and Data Science"),
        (r"\b(?:Computer\s+Science\s+(?:and|&)\s+Business\s+Systems|CSBS)\b", "Computer Science and Business Systems"),
        (r"\b(?:Computer\s+(?:and|&)\s+Communication\s+Engineering|CCE)\b", "Computer and Communication Engineering"),
        (r"\b(?:Computer\s+Science\s+(?:and|&)\s+Engineering|Computer\s+Science|CSE)\b", "Computer Science and Engineering"),
        (r"\b(?:Electronics\s+(?:and|&)\s+Communication\s+Engineering|ECE)\b", "Electronics and Communication Engineering"),
        (r"\b(?:Electrical\s+(?:and|&)\s+Electronics\s+Engineering|EEE)\b", "Electrical and Electronics Engineering"),
        (r"\b(?:Information\s+Technology|IT)\b", "Information Technology"),
        (r"\b(?:Mechanical\s+Engineering|Mech)\b", "Mechanical Engineering"),
        (r"\b(?:Civil\s+Engineering)\b", "Civil Engineering"),
    )

    INSTITUTION_EXTRACTION_PATTERNS = (
        r"\b(?:University\s+of\s+[A-Za-z]+(?:,\s*[A-Za-z\s]+)?|(?:[A-Za-z0-9.']+\s+){1,4}(?:College|University|Institute|School|Academy|Campus|Polytechnic)(?:\s+of\s+[A-Za-z0-9.']+)?(?:,\s*[A-Za-z\s]+)?)\b",
        r"\b(?:GGHSS|GHSS|KMVM|BVM|MVM)\b(?:,\s*[A-Za-z\s]+)?",
    )

    @classmethod
    def _clean_institution_name(cls, raw: str | None) -> str | None:
        if not raw:
            return None
        text = raw
        for pat, _ in cls.DEGREE_EXTRACTION_PATTERNS:
            text = re.sub(pat, "", text, flags=re.I)
        for pat, _ in cls.FIELD_EXTRACTION_PATTERNS:
            text = re.sub(pat, "", text, flags=re.I)
        text = re.sub(r"^(?:Computer\s+Science\s+and\s+Engineering|Computer\s+Science|Information\s+Technology)\s*", "", text, flags=re.I)
        text = re.sub(r"\b(?:CGPA|GPA|Percentage|Percentage\s*:|PASS|\d+(?:\.\d+)?%?)\b.*$", "", text, flags=re.I)
        text = re.sub(r"\b(?:19|20)\d{2}\s*[-–—to]+\s*(?:19|20)\d{2}\b", "", text)
        text = re.sub(r"\b(?:19|20)\d{2}\b", "", text)
        text = re.sub(r"\|\s*GitHub\s*LinkedIn.*$", "", text, flags=re.I)
        text = re.sub(r"\|\s*LinkedIn.*$", "", text, flags=re.I)
        text = re.sub(r"^[•●○▪*–—\s,:;|/-]+", "", text)
        text = re.sub(r"[,:;|/-]+$", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:255] if text and len(text) >= 3 else None

    @classmethod
    def _education(cls, block: str) -> list[dict[str, str | None]]:
        if not block.strip():
            return []

        text = block.strip()
        
        # 1. Identify degrees in order
        degrees_found: list[tuple[int, int, str, str]] = []
        for pat, canonical in cls.DEGREE_EXTRACTION_PATTERNS:
            for m in re.finditer(pat, text, re.IGNORECASE):
                degrees_found.append((m.start(), m.end(), canonical, m.group(0)))
        degrees_found.sort(key=lambda x: x[0])
        clean_degrees: list[tuple[int, int, str, str]] = []
        last_end = -1
        for d in degrees_found:
            if d[0] >= last_end:
                clean_degrees.append(d)
                last_end = d[1]

        if not clean_degrees:
            return [{
                "degree": None,
                "institution": cls._clean_institution_name(text),
                "year": (YEAR_PATTERN.search(text) or [None])[0],
                "field_of_study": (FIELD_PATTERN.search(text) or [None])[0],
                "grade": (GRADE_PATTERN.search(text) or [None])[0],
            }]

        items: list[dict[str, str | None]] = []

        # Multiline structured block handling
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) > 1 and len(clean_degrees) > 1:
            current_entry: dict[str, str | None] = {
                "degree": None, "institution": None, "year": None, "field_of_study": None, "grade": None
            }
            for line in lines:
                line_deg = None
                for pat, canonical in cls.DEGREE_EXTRACTION_PATTERNS:
                    if re.search(pat, line, re.IGNORECASE):
                        line_deg = canonical
                        break

                line_inst = None
                for pat in cls.INSTITUTION_EXTRACTION_PATTERNS:
                    m = re.search(pat, line, re.IGNORECASE)
                    if m:
                        line_inst = cls._clean_institution_name(m.group(0))
                        if line_inst:
                            break
                if not line_inst and not line_deg and len(line.split()) <= 6 and not re.search(r"\d", line):
                    line_inst = cls._clean_institution_name(line)

                yr_m = re.search(r"\b((?:19|20)\d{2}(?:\s*[-–—to]+\s*(?:19|20)\d{2})?)\b", line)
                line_yr = yr_m.group(0) if yr_m else None

                grd_m = GRADE_PATTERN.search(line)
                line_grd = grd_m.group(0) if grd_m else None

                line_fld = None
                for pat, canonical in cls.FIELD_EXTRACTION_PATTERNS:
                    if re.search(pat, line, re.IGNORECASE):
                        line_fld = canonical
                        break

                if (line_deg and current_entry.get("degree")) or (line_inst and current_entry.get("institution") and (current_entry.get("degree") or current_entry.get("year"))):
                    items.append(current_entry)
                    current_entry = {"degree": line_deg, "institution": line_inst, "year": line_yr, "field_of_study": line_fld, "grade": line_grd}
                else:
                    if line_deg and not current_entry.get("degree"): current_entry["degree"] = line_deg
                    if line_inst and not current_entry.get("institution"): current_entry["institution"] = line_inst
                    if line_yr and not current_entry.get("year"): current_entry["year"] = line_yr
                    if line_fld and not current_entry.get("field_of_study"): current_entry["field_of_study"] = line_fld
                    if line_grd and not current_entry.get("grade"): current_entry["grade"] = line_grd

            if current_entry.get("degree") or current_entry.get("institution"):
                items.append(current_entry)
            return items

        # Single-line or continuous flattened table extraction
        all_years = [m.group(0) for m in re.finditer(r"\b((?:19|20)\d{2}(?:\s*[-–—to]+\s*(?:19|20)\d{2})?)\b", text)]
        all_grades = [m.group(0) for m in GRADE_PATTERN.finditer(text)]
        all_institutions: list[str] = []
        clean_text_for_inst = text
        for pat, _ in cls.DEGREE_EXTRACTION_PATTERNS:
            clean_text_for_inst = re.sub(pat, " ", clean_text_for_inst, flags=re.I)
        for pat in cls.INSTITUTION_EXTRACTION_PATTERNS:
            for m in re.finditer(pat, clean_text_for_inst, re.IGNORECASE):
                cand = cls._clean_institution_name(m.group(0))
                if cand and len(cand) >= 3 and cand not in all_institutions:
                    all_institutions.append(cand)

        for i in range(len(clean_degrees)):
            deg_name = clean_degrees[i][2]
            slice_start = clean_degrees[i][0]
            slice_end = clean_degrees[i+1][0] if i + 1 < len(clean_degrees) else len(text)
            chunk = text[slice_start:slice_end].strip()
            if i == 0 and clean_degrees[0][0] > 0:
                chunk = text[:slice_end].strip()

            fld = None
            if deg_name not in {"Higher Secondary (12th)", "Secondary School (10th)"}:
                for pat, canonical in cls.FIELD_EXTRACTION_PATTERNS:
                    if re.search(pat, chunk, re.IGNORECASE):
                        fld = canonical
                        break

            yr_m = re.search(r"\b((?:19|20)\d{2}(?:\s*[-–—to]+\s*(?:19|20)\d{2})?)\b", chunk)
            yr = yr_m.group(0) if yr_m else (all_years[i] if i < len(all_years) else None)

            grd_m = GRADE_PATTERN.search(chunk)
            grd = grd_m.group(0) if grd_m else (all_grades[i] if i < len(all_grades) else None)

            inst = None
            for pat in cls.INSTITUTION_EXTRACTION_PATTERNS:
                m = re.search(pat, chunk, re.IGNORECASE)
                if m:
                    cand = cls._clean_institution_name(m.group(0))
                    if cand:
                        inst = cand
                        break
            if not inst and i < len(all_institutions):
                inst = all_institutions[i]
            elif not inst and all_institutions:
                inst = all_institutions[0]

            items.append({
                "degree": deg_name,
                "institution": inst,
                "year": yr,
                "field_of_study": fld,
                "grade": grd,
            })

        return items


    INVALID_COMPANY_WORDS = {
        "present", "current", "now", "till date", "to date", "continuous",
        "experience", "work experience", "employment history", "professional experience",
        "internship", "internships", "projects", "technical projects", "education",
        "skills", "certifications", "responsibilities", "achievements", "summary",
        "role", "designation", "description",
    }

    @classmethod
    def _is_valid_company_name(cls, text: str | None) -> bool:
        if not text:
            return False
        clean = text.strip("•●▪*- \t\r\n,.;:()")
        if not clean or len(clean) < 2:
            return False
        if clean.casefold() in cls.INVALID_COMPANY_WORDS:
            return False
        if re.match(
            r"^(?:(?:19|20)\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|summer|winter|spring|fall|\d+\s*months?|\d+\s*years?)\b",
            clean,
            flags=re.I,
        ):
            return False
        if DURATION_PATTERN.search(clean) or DATE_RANGE_PATTERN.search(clean) or YEAR_PATTERN.search(clean):
            return False
        if match_terms(clean, DESIGNATIONS):
            return False
        # Action verbs starting descriptions
        if re.match(
            r"^(?:developing|developed|develops|building|built|builds|designing|designed|designs|implementing|implemented|implements|creating|created|creates|working|worked|works|managing|managed|manages|leading|led|leads|maintaining|maintained|maintains|collaborating|collaborated|collaborates|engineering|engineered|engineers|contributing|contributed|contributes|utilizing|utilized|utilizes|assisting|assisted|assists|handling|handled|handles|spearheading|spearheaded|spearheads|writing|wrote|writes|testing|tested|tests|deploying|deployed|deploys|automating|automated|automates|optimizing|optimized|optimizes|resolving|resolved|resolves|configuring|configured|configures)\b",
            clean,
            flags=re.I,
        ):
            return False
        words = clean.split()
        if len(words) == 1 and len(clean) <= 7 and not COMPANY_PATTERN.search(clean):
            return False
        if len(words) > 6:
            return False
        return True

    @classmethod
    def _detect_employment_type(cls, label: str | None, context: str | None) -> str:
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

    @classmethod
    def _extract_company_from_line(cls, line: str, prev_line: str | None, role_match: re.Match | None) -> str | None:
        if not line or not line.strip():
            return None
        # Never extract company from bullet lines or action verb lines
        if re.match(r"^[•●▪*\-–—]\s*", line) or re.match(
            r"^(?:developing|developed|develops|building|built|builds|designing|designed|designs|implementing|implemented|implements|creating|created|creates|working|worked|works|managing|managed|manages|leading|led|leads|maintaining|maintained|maintains|collaborating|collaborated|collaborates|engineering|engineered|engineers|contributing|contributed|contributes|utilizing|utilized|utilizes|assisting|assisted|assists|handling|handled|handles|spearheading|spearheaded|spearheads|writing|wrote|writes|testing|tested|tests|deploying|deployed|deploys|automating|automated|automates|optimizing|optimized|optimizes|resolving|resolved|resolves|configuring|configured|configures)\b",
            line.strip(),
            flags=re.I,
        ):
            return None

        cleaned = re.sub(
            r",\s*(?:Coimbatore|Chennai|Bengaluru|Bangalore|Mumbai|Delhi|Hyderabad|Pune|Kolkata|London|San Francisco|CA|UK|India|USA|[A-Z][a-zA-Z\s]{2,15})$",
            "",
            line.strip(),
            flags=re.I,
        ).strip()

        at_match = re.search(r"\bat\s+(.+?)(?:\s*[|,(]|$)", line, re.I)
        if at_match:
            comp = at_match.group(1).strip(" ,.;:()")
            if cls._is_valid_company_name(comp):
                return comp[:255]

        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            for p in parts:
                p_clean = re.sub(
                    r",\s*(?:Coimbatore|Chennai|Bengaluru|Bangalore|Mumbai|Delhi|Hyderabad|Pune|London|San Francisco|CA|UK|India|[A-Z][a-zA-Z\s]{2,15})$",
                    "",
                    p,
                    flags=re.I,
                ).strip()
                if cls._is_valid_company_name(p_clean):
                    return p_clean[:255]

        if " - " in line or " – " in line or " — " in line:
            parts = [p.strip() for p in re.split(r"\s*[-–—]\s*", line)]
            for p in parts:
                p_clean = re.sub(
                    r",\s*(?:Coimbatore|Chennai|Bengaluru|Bangalore|Mumbai|Delhi|Hyderabad|Pune|London|San Francisco|CA|UK|India|[A-Z][a-zA-Z\s]{2,15})$",
                    "",
                    p,
                    flags=re.I,
                ).strip()
                if cls._is_valid_company_name(p_clean):
                    return p_clean[:255]

        if (role_match or "role :" in line.lower() or "role:" in line.lower()) and prev_line:
            prev_clean = re.sub(
                r",\s*(?:Coimbatore|Chennai|Bengaluru|Bangalore|Mumbai|Delhi|Hyderabad|Pune|London|San Francisco|CA|UK|India|[A-Z][a-zA-Z\s]{2,15})$",
                "",
                prev_line.strip(),
                flags=re.I,
            ).strip()
            if cls._is_valid_company_name(prev_clean):
                return prev_clean[:255]

        # Explicit company indicator on short non-sentence lines (or standalone company line)
        if not role_match and len(cleaned.split()) <= 6:
            if not match_terms(line, DESIGNATIONS) and cls._is_valid_company_name(cleaned):
                return cleaned[:255]

        if prev_line and (role_match or "role" in line.lower()):
            prev_clean = re.sub(
                r",\s*(?:Coimbatore|Chennai|Bengaluru|Bangalore|Mumbai|Delhi|Hyderabad|Pune|London|San Francisco|CA|UK|India|[A-Z][a-zA-Z\s]{2,15})$",
                "",
                prev_line.strip(),
                flags=re.I,
            ).strip()
            if cls._is_valid_company_name(prev_clean):
                return prev_clean[:255]

        return None

    @classmethod
    def _experience(cls, block: str) -> list[dict[str, Any]]:
        lines = content_lines(block)
        if not lines:
            return []

        items: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for idx, line in enumerate(lines):
            prev_line = lines[idx - 1] if idx > 0 else None

            # Skip embedded project labels
            if re.match(r"(?i)^(?:project|academic\s*project)\s*:\s*", line):
                continue

            # Check if line is a bullet/action-verb line
            is_bullet = bool(re.match(r"^[•●▪*\-–—]\s*", line)) or bool(
                re.match(
                    r"^(?:developing|developed|develops|building|built|builds|designing|designed|designs|implementing|implemented|implements|creating|created|creates|working|worked|works|managing|managed|manages|leading|led|leads|maintaining|maintained|maintains|collaborating|collaborated|collaborates|engineering|engineered|engineers|contributing|contributed|contributes|utilizing|utilized|utilizes|assisting|assisted|assists|handling|handled|handles|spearheading|spearheaded|spearheads|writing|wrote|writes|testing|tested|tests|deploying|deployed|deploys|automating|automated|automates|optimizing|optimized|optimizes|resolving|resolved|resolves|configuring|configured|configures)\b",
                    line.strip(),
                    flags=re.I,
                )
            )

            duration = DURATION_PATTERN.search(line)
            date_range = DATE_RANGE_PATTERN.search(line)
            titles = match_terms(line, DESIGNATIONS)

            role_match = re.search(r"(?i)\brole\s*:\s*(.+)$", line)
            role_title = role_match.group(1).strip() if role_match else None

            extracted_company = cls._extract_company_from_line(line, prev_line, role_match) if not is_bullet else None
            
            if role_title:
                title_val = role_title
            elif titles and not is_bullet:
                if len(line.split()) <= 6:
                    clean_title_line = re.sub(r",\s*(?:Coimbatore|Chennai|Bengaluru|Bangalore|Mumbai|Delhi|Hyderabad|Pune|Kolkata|London|San Francisco|CA|UK|India|USA|[A-Z][a-zA-Z\s]{2,15})$", "", line.strip(), flags=re.I).strip(" ,.;:()")
                    title_val = clean_title_line
                else:
                    title_val = titles[0]
            else:
                title_val = None

            text_dur_val: str | None = duration.group(0) if duration else None
            date_dur_val: str | None = date_range.group(0) if date_range else None
            dur_val: str | None = text_dur_val or date_dur_val

            start_date, end_date = None, None
            if date_range:
                raw_range = date_range.group(0)
                parts = re.split(r"\s*(?:-|–|—|to)\s*", raw_range, flags=re.I)
                if len(parts) == 2:
                    start_date, end_date = parts[0].strip(), parts[1].strip()

            emp_type = cls._detect_employment_type(None, f"{title_val or ''} {line}")

            loc_match = re.search(
                r",\s*(Coimbatore|Chennai|Bengaluru|Bangalore|Mumbai|Delhi|Hyderabad|Pune|London|San Francisco|CA|UK|India)\b",
                line,
                flags=re.I,
            )
            loc_val = loc_match.group(1).strip() if loc_match else None

            is_new_entry = False
            if current and (current.get("company") or current.get("designation")):
                if not is_bullet:
                    if extracted_company and current.get("company") and extracted_company.casefold() != current.get("company", "").casefold():
                        is_new_entry = True
                    elif title_val and current.get("designation") and title_val.casefold() != current.get("designation", "").casefold() and (extracted_company or date_range):
                        is_new_entry = True

            if is_new_entry:
                if current.get("description_lines"):
                    current["description"] = " ".join(current["description_lines"])
                items.append(cls._format_experience_item(current))
                current = cls._new_experience_item(
                    company=extracted_company,
                    designation=title_val,
                    employment_type=emp_type,
                    start_date=start_date,
                    end_date=end_date,
                    duration=dur_val,
                    location=loc_val,
                )
            elif current:
                if not current.get("designation") and title_val:
                    current["designation"] = title_val
                    current["title"] = title_val
                if emp_type != "Full-time":
                    current["employment_type"] = emp_type
                if not current.get("company") and extracted_company:
                    current["company"] = extracted_company
                if loc_val and not current.get("location"):
                    current["location"] = loc_val
                if text_dur_val and not current.get("duration"):
                    current["duration"] = text_dur_val
                if date_dur_val:
                    if not current.get("duration"):
                        current["duration"] = date_dur_val
                    if start_date and not current.get("start_date"):
                        current["start_date"] = start_date
                    if end_date and not current.get("end_date"):
                        current["end_date"] = end_date
                if end_date and end_date.casefold() in {"present", "current", "now"}:
                    current["is_current"] = True
                elif dur_val and ("present" in dur_val.lower() or "current" in dur_val.lower()):
                    current["is_current"] = True

                # Filter OCR noise: isolated fragments <= 8 chars
                if len(line) <= 8 and re.match(r'^[A-Z][a-z]+$', line) and not re.search(r'\s', line):
                    continue

                is_pure_header = bool(
                    (title_val or extracted_company)
                    and not is_bullet
                    and len(line.split()) <= 8
                    and not re.search(r"[.;]$", line)
                )
                if not is_pure_header:
                    clean_bullet = re.sub(r"^[•●▪*\-–—]\s*", "", line).strip()
                    if clean_bullet:
                        current["description_lines"].append(clean_bullet)
                        current["responsibilities"].append(clean_bullet)
            elif (title_val or extracted_company or dur_val or (emp_type != "Full-time")) and not is_bullet:
                current = cls._new_experience_item(
                    company=extracted_company,
                    designation=title_val,
                    employment_type=emp_type,
                    start_date=start_date,
                    end_date=end_date,
                    duration=dur_val,
                    location=loc_val,
                )
                if end_date and end_date.casefold() in {"present", "current", "now"}:
                    current["is_current"] = True
                elif dur_val and ("present" in dur_val.lower() or "current" in dur_val.lower()):
                    current["is_current"] = True

        if current and (current.get("designation") or current.get("title") or current.get("company")):
            if current.get("description_lines"):
                current["description"] = " ".join(current["description_lines"])
            elif not current.get("description"):
                current["description"] = " ".join(
                    filter(None, [current.get("company"), current.get("designation"), current.get("duration")])
                )
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
        location: str | None = None,
    ) -> dict[str, Any]:
        is_curr = False
        if end_date and end_date.casefold() in {"present", "current", "now"}:
            is_curr = True
        elif duration and ("present" in duration.lower() or "current" in duration.lower()):
            is_curr = True
        return {
            "company": company[:255] if company else None,
            "designation": designation,
            "title": designation,
            "employment_type": employment_type,
            "start_date": start_date,
            "end_date": end_date,
            "is_current": is_curr,
            "duration": duration,
            "description": "",
            "description_lines": [],
            "responsibilities": [],
            "location": location,
        }

    @staticmethod
    def _format_experience_item(item: dict[str, Any]) -> dict[str, Any]:
        res = dict(item)
        res.pop("description_lines", None)
        return res

    @classmethod
    def _skills(cls, skills_block: str, full_text: str) -> list[str]:
        extracted_skills: list[str] = []
        seen: set[str] = set()

        def add_skill(s: str) -> None:
            if not s:
                return
            cleaned = clean_unicode(s).strip()
            cleaned = re.sub(r"^[•●○▪*–—\d\.\)\s,:;|/-]+", "", cleaned).strip()
            cleaned = re.sub(r"[,:;|/-]+$", "", cleaned).strip()
            if not cleaned:
                return
            # Remove trailing parenthetical qualifiers (e.g. "(proficient)", "(intermediate)", "(basic)")
            cleaned = re.sub(
                r"\s*\((?:proficient|intermediate|beginner|expert|basics?|advanced|familiar|hands-on)\)\s*$",
                "",
                cleaned,
                flags=re.I,
            ).strip()
            words = cleaned.split()
            if 1 <= len(words) <= 7 and len(cleaned) <= 60:
                # Exclude purely generic category headings if isolated
                if re.fullmatch(
                    r"(?:technical\s+)?(?:skills?|technologies|tools?|languages?|programming\s+languages?|frameworks?|libraries|core|databases?|query\s+languages?|platforms?|cloud|methodologies|web\s+technologies|other)\s*[:：]?",
                    cleaned,
                    re.I,
                ):
                    return
                key = cleaned.casefold()
                if key not in seen:
                    seen.add(key)
                    extracted_skills.append(cleaned)

        def split_items(text_line: str) -> list[str]:
            # Split on commas, semicolons, pipes, tabs, bullet characters, or ' / ' (with whitespace)
            # Avoid splitting 'C/C++', 'CI/CD', 'TCP/IP', 'OS/Networking' without spaces
            parts = re.split(r"[,;|•●○▪*\t]|\s{2,}|\s+/\s+", text_line)
            return [p.strip() for p in parts if p.strip()]

        if skills_block:
            category_prefix_re = re.compile(
                r"^(?:[•●○▪*–—\d\.\)\s]*)([A-Za-z0-9\s/&+-]{1,35}?)\s*[:：]\s*(.*)$"
            )
            for raw_line in skills_block.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                cat_match = category_prefix_re.match(line)
                if cat_match:
                    items_str = cat_match.group(2).strip()
                    if items_str:
                        for item in split_items(items_str):
                            add_skill(item)
                else:
                    clean_line = re.sub(r"^[•●○▪*–—\d\.\)\s]+", "", line).strip()
                    # If it's a short line or delimited list (not a paragraph sentence)
                    if len(clean_line.split()) <= 10 and not clean_line.endswith((".", "!", "?")):
                        for item in split_items(clean_line):
                            add_skill(item)

        # Also match canonical SKILLS dictionary terms across full_text (ensures backward compatibility)
        for term in match_terms(full_text, SKILLS):
            add_skill(term)

        return extracted_skills

    PROJECT_TECH_VOCABULARY = (
        # Cloud & DevOps
        "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Istio", "Terraform", "Ansible",
        "ArgoCD", "Helm", "Datadog", "CloudWatch", "Prometheus", "Grafana", "CI/CD",
        "GitHub Actions", "Jenkins", "GitLab", "ECR", "EKS", "ECS", "S3", "EC2", "Lambda",
        "API Gateway", "MinIO", "Linux", "Windows", "Unix",
        # Security & Monitoring
        "Splunk", "Microsoft Sentinel", "Sentinel", "KQL", "CrowdStrike", "Microsoft Defender",
        "Defender", "MITRE ATT&CK", "SIEM", "EDR", "XDR", "Active Directory", "Firewall",
        "TCP/IP", "Wireshark", "Burp Suite", "Metasploit", "Nmap", "Nessus",
        # Languages & Scripting
        "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", ".NET", "Go", "Golang",
        "Rust", "PHP", "Ruby", "Scala", "Bash", "Shell", "PowerShell", "SQL",
        # Frameworks & Libraries
        "FastAPI", "Django", "Flask", "React.js", "React", "Next.js", "Node.js", "Node",
        "Express.js", "Express", "Vue.js", "Vue", "Angular", "Spring Boot", "Spring",
        "GraphQL", "REST APIs", "REST API", "gRPC", "Redux", "Tailwind", "OpenCV", "PyTorch",
        "TensorFlow", "Scikit-learn", "Pandas", "NumPy", "Selenium", "Postman", "Playwright",
        "YOLOv8", "YOLO",
        # Databases & Storage
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Cassandra", "DynamoDB", "Elasticsearch",
        "SQLite", "Oracle", "Snowflake", "PySpark", "Spark", "Airflow", "Kafka", "RabbitMQ",
        "Prisma ORM", "Prisma", "SQLAlchemy", "dbt",
        # Tools & Platforms
        "Jira", "Confluence", "MS Project", "Power BI", "Tableau", "ServiceNow", "Git", "GitHub", "Vercel"
    )

    @classmethod
    def _normalize_single_tech(cls, raw: str) -> str:
        cleaned = raw.strip()
        c_lower = cleaned.casefold()
        alias_map = {
            "node": "Node.js", "nodejs": "Node.js", "node.js": "Node.js",
            "express": "Express.js", "expressjs": "Express.js", "express.js": "Express.js",
            "nextjs": "Next.js", "next.js": "Next.js",
            "reactjs": "React.js",
            "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
            "k8s": "Kubernetes", "kubernetes": "Kubernetes",
            "mitre attack": "MITRE ATT&CK", "mitre att&ck": "MITRE ATT&CK",
            "sentinel": "Microsoft Sentinel", "microsoft sentinel": "Microsoft Sentinel",
            "defender": "Microsoft Defender", "microsoft defender": "Microsoft Defender",
            "powershell": "PowerShell", "power shell": "PowerShell",
            "cloudwatch": "CloudWatch", "aws cloudwatch": "CloudWatch",
            "prisma": "Prisma", "prisma orm": "Prisma",
            "selenium webdriver": "Selenium", "selenium": "Selenium"
        }
        return alias_map.get(c_lower, cleaned)

    @classmethod
    def _extract_project_technologies(cls, text_line: str) -> list[str]:
        if not text_line or not text_line.strip():
            return []

        results: list[str] = []
        seen: set[str] = set()

        def add_tech(item: str) -> None:
            cleaned = clean_unicode(item).strip().strip("•●○▪*–—,;:-/|()[]{}")
            if not cleaned or len(cleaned) < 2 or len(cleaned) > 50:
                return
            if re.fullmatch(
                r"(?:technolog(?:y|ies)|tech\s+stack|tools?(?:\s+used)?|built\s+with|environment|stack|using|with)\s*[:：]?",
                cleaned,
                re.I,
            ):
                return
            norm = cls._normalize_single_tech(cleaned)
            norm_key = norm.casefold()
            if norm_key not in seen:
                seen.add(norm_key)
                results.append(norm)

        # 1. Explicit tools/technologies labels anywhere in project text
        explicit_patterns = re.findall(
            r"(?:technolog(?:y|ies)|tech\s+stack|tools?(?:\s+used)?|built\s+with|environment|stack)\s*[:：]\s*([^•\n]+)",
            text_line,
            re.IGNORECASE,
        )
        for exp in explicit_patterns:
            parts = re.split(r"[,;|•●○▪*\t]|\s{2,}|\s+/\s+", exp)
            for p in parts:
                add_tech(p)

        # 2. Pipe/dash inline stack e.g. "Title | Tech1, Tech2"
        pipe_patterns = re.findall(r"\s*[|–—]\s*([A-Za-z0-9\s,.\+#/]+?)(?=\s*[•\n]|\s+Built\b|\s+Developed\b|$)", text_line)
        for pp in pipe_patterns:
            parts = re.split(r"[,;|•●○▪*\t]|\s{2,}|\s+/\s+", pp)
            for p in parts:
                add_tech(p)

        # 3. Match terms from comprehensive project tech vocabulary
        for term in match_terms(text_line, cls.PROJECT_TECH_VOCABULARY):
            add_tech(term)

        return results

    @classmethod
    def _parse_single_project_chunk(cls, chunk: str) -> dict[str, Any]:
        clean = re.sub(r"^[•●▪*\ufffd\s-]+", "", chunk).strip()
        if not clean:
            return {}

        # 1. Title followed by Technologies: / Tech stack: label
        tech_label_match = re.match(
            r"^([A-Z][A-Za-z0-9\s/&+\-–—\'.]{1,90}?)\s*(?:technolog(?:y|ies)|tech\s+stack|tools?(?:\s+used)?|built\s+with|environment|stack)\s*[:：]\s*([A-Za-z0-9\s,.\+#/]+?)(?=\s*[•●▪*\ufffd]|\s+Built\b|\s+Developed\b|\s+Designed\b|\s+Created\b|\s+Implemented\b|\s+Engineered\b|\n|$)(.*)",
            clean,
            re.I | re.DOTALL,
        )
        if tech_label_match:
            title = tech_label_match.group(1).strip()
            tech_str = tech_label_match.group(2).strip()
            rest = tech_label_match.group(3).strip()
            desc = re.sub(r"^[•●▪*\ufffd\s-]+", "", rest).strip() if rest else clean
            techs = cls._extract_project_technologies(tech_str + " " + desc)
            return {
                "name": title[:255],
                "description": desc or clean,
                "technologies": techs,
            }

        # 2. Title | Techs or Title – Techs
        pipe_match = re.match(
            r"^([A-Z][A-Za-z0-9\s/&+\-–—\'.]{1,90}?)\s*(?:\||\s+[–—]\s+)\s*([A-Za-z0-9\s,.\+#/]+?)(?=\s*[•●▪*\ufffd]|\s+Built\b|\s+Developed\b|\s+Designed\b|\s+Created\b|\s+Implemented\b|\s+Engineered\b|\n|$)(.*)",
            clean,
            re.DOTALL,
        )
        if pipe_match:
            title = pipe_match.group(1).strip()
            tech_str = pipe_match.group(2).strip()
            rest = pipe_match.group(3).strip()
            desc = re.sub(r"^[•●▪*\ufffd\s-]+", "", rest).strip() if rest else clean
            techs = cls._extract_project_technologies(tech_str + " " + desc)
            return {
                "name": title[:255],
                "description": desc or clean,
                "technologies": techs,
            }

        # 3. Year Title or Title Year
        # e.g. 'SECURE VOTING SYSTEM 2025 Developed...' or 'SMART TROLLEYS . 2025 Developed...' or '2024 FASHIONBOOK-(FRONTEND) Developed...'
        year_match = re.match(
            r"^(?:(?:(?:19|20)\d{2}\s+)([A-Z0-9][A-Za-z0-9\s/&+\-–—\'.()]{2,70}?)|([A-Z0-9][A-Za-z0-9\s/&+\-–—\'.()]{2,70}?)\s*(?:\.|\s+)*(?:19|20)\d{2})\s+(?:Developed\b|Built\b|Designed\b|Created\b|Implemented\b|Engineered\b|Integrated\b|supported\b|centralized\b|with focus\b)(.*)",
            clean,
            re.I | re.DOTALL,
        )
        if year_match:
            title = (year_match.group(1) or year_match.group(2)).strip().strip(". -–—")
            rest = clean[year_match.end(1) if year_match.group(1) else year_match.end(2):].strip().lstrip(". 0123456789-–—")
            desc = re.sub(r"^[•●▪*\ufffd\s-]+", "", rest).strip() if rest else clean
            techs = cls._extract_project_technologies(title + " " + desc)
            return {
                "name": title[:255],
                "description": desc or clean,
                "technologies": techs,
            }

        # 4. Title • Description (e.g. Retail Sales Data Pipeline • Built a batch ETL...)
        bullet_match = re.match(
            r"^([A-Z][A-Za-z0-9\s/&+\-–—\'.]{1,60}?\b(?:Pipeline|System|Platform|App|Application|Tool|Dashboard|Service|Services|API|Engine|Portal|Database|Website|Model|Bot|Tracker|Finder|Sync|DApp|Network|Scrapper|Scanner)\b)\s*[•●▪*\ufffd\s-]+(.*)",
            clean,
            re.DOTALL,
        )
        if bullet_match:
            title = bullet_match.group(1).strip()
            rest = bullet_match.group(2).strip()
            desc = re.sub(r"^[•●▪*\ufffd\s-]+", "", rest).strip() if rest else clean
            techs = cls._extract_project_technologies(title + " " + desc)
            return {
                "name": title[:255],
                "description": desc or clean,
                "technologies": techs,
            }

        # 5. Explicit Project: Name
        proj_prefix_match = re.match(
            r"^(?:PROJECTS?|KEY\s+PROJECTS?)\s*[:•●▪*\ufffd–—\-]\s*([A-Za-z0-9][A-Za-z0-9\s\-–—/&+#.()]+?)(?=\s*[•●▪*\ufffd]|\n|$)(.*)",
            clean,
            re.IGNORECASE | re.DOTALL,
        )
        if proj_prefix_match:
            title = proj_prefix_match.group(1).strip()
            rest = proj_prefix_match.group(2).strip()
            desc = re.sub(r"^[•●▪*\ufffd\s-]+", "", rest).strip() if rest else clean
            techs = cls._extract_project_technologies(title + " " + desc)
            return {
                "name": title[:255],
                "description": desc or clean,
                "technologies": techs,
            }

        # 6. Multi-line chunk with first line as title
        lines = [l.strip() for l in clean.splitlines() if l.strip()]
        if len(lines) > 1 and len(lines[0].split()) <= 8 and not lines[0].endswith("."):
            title = lines[0].strip()
            title = re.split(r"\s+[|–—]\s+", title)[0].strip()
            desc = " ".join(lines[1:]).strip()
            return {
                "name": title[:255],
                "description": desc or clean,
                "technologies": cls._extract_project_technologies(clean),
            }

        # 7. Fallback single project
        title_words = clean.split()[:5]
        title = " ".join(title_words)
        title = re.split(r"\s+[|–—]\s+", title)[0].strip()
        return {
            "name": title[:255] if title else "Project",
            "description": clean,
            "technologies": cls._extract_project_technologies(clean),
        }

    @classmethod
    def _projects(cls, block: str) -> list[dict[str, Any]]:
        if not block.strip():
            return []

        normalized_block = re.sub(r"[\ufffd\u2022\u25cf\u25aa\u25cb]", " \u2022 ", block)

        heading_boundary_re = re.compile(
            r"(?:^|(?<=\.)\s+|(?<=\u2022)\s+|\n|(?<=APIs)\s+|(?<=React\.js)\s+|(?<=Next\.js)\s+)"
            r"(?:"
            r"(?P<p1>(?:PROJECTS?\s*\d*\s*[:•●▪*\ufffd–—\-]|KEY\s+PROJECTS?\s*[:•●▪*\ufffd–—\-])\s*[^•\n\.\ufffd]+)"
            r"|"
            r"(?P<p2>[A-Z0-9][^•\n\.\ufffd|]{1,60}?\s*(?:\||\s+[–—]\s+)\s*[^•\n\ufffd]+?(?=\s*\u2022|\s+Built\b|\s+Developed\b|\s+Designed\b|\s+Created\b|\s+Implemented\b|\s+Engineered\b|\n|$))"
            r"|"
            r"(?P<p3>(?:(?:(?:19|20)\d{2}\s+)[A-Z0-9][^•\n\.\ufffd|]{2,60}?|[A-Z0-9][^•\n\.\ufffd|]{2,60}?\s*(?:\.|\s+)*(?:19|20)\d{2})(?=\s+Developed\b|\s+Built\b|\s+Designed\b|\s+Created\b|\s+Implemented\b|\s+Engineered\b|\s+Integrated\b|\s+with focus\b|\s*\u2022|\n|$))"
            r")",
            re.IGNORECASE,
        )

        matches = list(heading_boundary_re.finditer(normalized_block))
        if matches and len(matches) > 1:
            project_chunks = []
            for i, m in enumerate(matches):
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(normalized_block)
                chunk = normalized_block[start:end].strip()
                if chunk:
                    project_chunks.append(chunk)

            parsed_projects = []
            for chunk in project_chunks:
                proj = cls._parse_single_project_chunk(chunk)
                if proj:
                    parsed_projects.append(proj)
            if parsed_projects:
                deduped: list[dict[str, Any]] = []
                seen_names = set()
                for p in parsed_projects:
                    k = p.get("name", "").strip().casefold()
                    if k and k not in seen_names:
                        seen_names.add(k)
                        deduped.append(p)
                    elif not k:
                        deduped.append(p)
                return deduped

        lines = [line.strip() for line in normalized_block.splitlines() if line.strip()]
        proj_heading_re = re.compile(
            r"^(?:[•●○▪*–—\d\.\)\s]*)(?:project\s*[:：]|\d+[\.\)]\s*project\s*[:：]|key\s+project\s*[:：])",
            re.IGNORECASE,
        )

        projects: list[dict[str, Any]] = []
        current_project: dict[str, Any] | None = None

        for line_str in lines:
            if not line_str:
                continue

            is_proj_title = bool(proj_heading_re.match(line_str))
            clean_text = proj_heading_re.sub("", line_str).strip()
            clean_text = re.sub(r"^[::•●○▪*–—\s-]+", "", clean_text).strip()

            is_pipe_heading = ("|" in line_str or bool(re.search(r"\s+[–—]\s+", line_str))) and not line_str.startswith(("-", "*", "•", "●", "○", "▪"))
            is_bullet_line = line_str.startswith(("-", "*", "•", "●", "○", "▪"))

            if is_proj_title or (is_pipe_heading and not is_bullet_line):
                if current_project:
                    projects.append(current_project)

                title_source = clean_text if clean_text else line_str
                title_name = re.split(r"\s+[|–—]\s+", title_source)[0].strip() or title_source
                title_name = re.sub(r"\s*\([^)]*\)\s*$", "", title_name).strip() or title_name
                title_name = title_name.rstrip(" :").strip()

                current_project = {
                    "name": title_name[:255],
                    "description": title_source,
                    "technologies": cls._extract_project_technologies(line_str),
                }
            elif current_project is None:
                title_name = re.split(r"\s+[|–—]\s+", clean_text)[0].strip() or clean_text
                title_name = re.sub(r"\s*\([^)]*\)\s*$", "", title_name).strip() or title_name
                title_name = title_name.rstrip(" :").strip()
                current_project = {
                    "name": title_name[:255],
                    "description": clean_text,
                    "technologies": cls._extract_project_technologies(clean_text),
                }
            else:
                raw_clean = re.sub(r"^[•●○▪*–—\s-]+", "", line_str).strip()
                is_tech_label = bool(re.match(r"^(?:technolog(?:y|ies)|tech\s+stack|tools?(?:\s+used)?|built\s+with|environment|stack)\s*[:：]", raw_clean, re.I))

                if not is_tech_label:
                    current_project["description"] += (" " if current_project["description"] else "") + clean_text
                for tech in cls._extract_project_technologies(line_str):
                    if tech not in current_project["technologies"]:
                        current_project["technologies"].append(tech)

        if current_project:
            projects.append(current_project)

        deduped: list[dict[str, Any]] = []
        seen_names = set()
        for p in projects:
            k = p.get("name", "").strip().casefold()
            if k and k not in seen_names:
                seen_names.add(k)
                deduped.append(p)
            elif not k:
                deduped.append(p)

        return deduped


    @classmethod
    def _extract_embedded_projects(cls, exp_block: str) -> list[dict[str, Any]]:
        if not exp_block.strip():
            return []
        clean = re.sub(r"[\ufffd\u2022\u25cf\u25aa\u25cb]", " \u2022 ", exp_block)

        # 1. Look for explicit PROJECT • / PROJECT: markers in experience
        proj_marker_re = re.compile(r"\b(?:PROJECTS?|KEY\s+PROJECTS?)\s*[:\u2022•–—\-]\s*", re.IGNORECASE)
        matches = list(proj_marker_re.finditer(clean))
        projects: list[dict[str, Any]] = []
        if matches:
            for i, m in enumerate(matches):
                start_idx = m.end()
                end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(clean)
                chunk = clean[start_idx:end_idx].strip()
                title_match = re.match(
                    r"^([A-Z0-9][A-Za-z0-9\s/&+\-–—\'.()]{2,80}?)(?=\s*\u2022|\s+[a-z]|\s+supported\b|\s+centralized\b|\s+Designed\b|\s+Built\b|\s+Developed\b|$)(.*)",
                    chunk,
                    re.DOTALL,
                )
                if title_match:
                    title = title_match.group(1).strip().strip(":•–— ")
                    desc = re.sub(r"^[•\s–—:-]+", "", title_match.group(2)).strip()
                    desc = re.sub(r"\s+", " ", desc)
                    techs = cls._extract_project_technologies(title + " " + desc)
                    projects.append({
                        "name": title[:255],
                        "description": desc or title,
                        "technologies": techs,
                    })
            if projects:
                return projects

        # 2. Look for Year + Title in two-column experience leak (e.g. 2024 FASHIONBOOK-(FRONTEND))
        year_title_re = re.compile(
            r"\b(?:(?:19|20)\d{2}\s+)([A-Z0-9][A-Za-z0-9\s/&+\-–—\'.()]{2,60}?)(?=\s+Developed|\s+Built|\s+Designed|\s+Created|\s+Implemented|\s*\u2022|\n)",
            re.IGNORECASE,
        )
        m_yt = year_title_re.search(clean)
        if m_yt:
            title = m_yt.group(1).strip().strip(":•–— ")
            rest = clean[m_yt.end():].strip()
            cert_idx = rest.find("CERTIFICATES")
            if cert_idx != -1:
                rest = rest[:cert_idx].strip()
            desc = re.sub(r"\s+", " ", rest)
            techs = cls._extract_project_technologies(title + " " + desc)
            projects.append({
                "name": title[:255],
                "description": desc or title,
                "technologies": techs,
            })

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
            
            # Split multi-item lines delimited by '|' or bullets
            if "|" in clean or "•" in clean:
                parts = [p.strip() for p in re.split(r"\s*[|•●▪*]\s*", clean) if p.strip()]
                for p in parts:
                    if p and len(p) >= 3:
                        raw_certs.append(p)
            elif clean and len(clean) >= 2:
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

        # Languages and location can be optional depending on candidate resume composition
        optional_fields = {"languages"}

        extracted_counts = 0
        evaluable_fields = 0
        warnings: list[str] = []

        for key, val in values.items():
            if val:
                extracted_counts += 1
                evaluable_fields += 1
            else:
                if key not in optional_fields:
                    evaluable_fields += 1
                    warnings.append(f"Field '{key}' could not be extracted.")

        total_fields = evaluable_fields if evaluable_fields > 0 else len(values)
        entity_extraction_score = round(extracted_counts / total_fields, 2)
        overall_quality_score = round((section_detection_score * 0.4) + (entity_extraction_score * 0.6), 2)

        return {
            "section_detection_score": section_detection_score,
            "entity_extraction_score": entity_extraction_score,
            "overall_quality_score": overall_quality_score,
            "warnings": warnings,
        }

