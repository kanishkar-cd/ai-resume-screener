"""Structured section parsers for line-oriented resume text.

The PDF/DOCX parsers emit one logical line per visual item: entry headers
("Title | Company  Jan 2024 – Present"), bullets normalized to "• ", label
lines ("Tech Stack: ...") and description sentences. These parsers classify
each line by role and group lines into entries. They return an empty list when
a block does not look line-structured, so callers can fall back to the legacy
regex parsers that handle flattened single-line text.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.pipeline.extraction_pipeline import SECTION_ALIASES

# Resume-only headings that close the previous section so its content does not bleed
# into education/projects/certifications (kept out of the JD-shared alias table).
RESUME_EXTRA_SECTIONS = {
    "profiles": {"coding profiles", "coding profile", "online profiles", "profiles", "competitive programming"},
    "other": {
        "additional information", "personal information", "declaration", "hobbies", "interests",
        "hobbies & interests", "extracurricular activities", "extra-curricular activities",
        "co-curricular activities", "positions of responsibility", "position of responsibility",
        "leadership", "leadership experience", "volunteering", "volunteer experience", "references",
        "activities", "strengths", "soft skills",
    },
}
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_TOKEN = rf"(?:{_MONTH}\s*,?\s*'?(?:19|20)?\d{{2}}|\d{{1,2}}\s*/\s*(?:19|20)\d{{2}}|(?:19|20)\d{{2}})"
_DATE_END = rf"(?:{_DATE_TOKEN}|present|current|now|till\s+date|to\s+date|ongoing)"
DATE_SPAN_RE = re.compile(
    rf"\(?(?<![\w/]){_DATE_TOKEN}(?:\s*(?:-|–|—|to|until)\s*{_DATE_END})?(?![\w/])\)?",
    re.I,
)
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
TEXT_DURATION_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*\+?\s*"
    r"(?:months?|weeks?|years?|yrs?)\b",
    re.I,
)

BULLET_RE = re.compile(r"^(?:[•●▪■◦○➢➤►▶▸✓✔❖◆◇∙⁃·*]|-(?=\s)|\.(?=\s+[A-Z]))\s*")
LABEL_RE = re.compile(
    r"^(?P<label>tech(?:nical)?\s*stack|tech(?:nolog(?:y|ies))?(?:\s+used)?|tools?(?:\s*(?:used|&\s*technologies))?|"
    r"stack|skills?\s+used|environment|built\s+with|languages?\s+used|domain|client|role|position|designation|"
    r"team|note|achievements?|key\s+achievements?|links?|github|demo)\s*(?::|—|–|-\s)\s*(?P<value>.*)$",
    re.I,
)
TECH_LABELS = {
    "tech stack", "technical stack", "techstack", "tech", "technology", "technologies", "technology used",
    "technologies used", "tech used", "tool", "tools", "tools used", "tools & technologies", "stack",
    "skills used", "environment", "built with", "languages used",
}
ROLE_LABELS = {"role", "position", "designation"}

ACTION_VERB_RE = re.compile(
    r"^(?:developed|developing|built|building|designed|designing|implemented|implementing|created|creating|"
    r"worked|working|managed|managing|led|leading|maintained|maintaining|collaborated|collaborating|"
    r"engineered|contributed|utilized|assisted|handled|spearheaded|wrote|tested|deployed|automated|"
    r"optimized|optimised|resolved|configured|gained|completed|learned|learnt|analysed|analyzed|"
    r"integrated|conducted|performed|participated|responsible|involved|achieved|improved|reduced|"
    r"increased|delivered|owned|trained|applied|queried|established|enhanced|executed|monitored|"
    r"supported|coordinated|organized|organised|published|presented|prepared|researched|explored)\b",
    re.I,
)
ROLE_WORD_RE = re.compile(
    r"\b(?:intern(?:ship)?|trainee|apprentice|engineer(?:ing)?|developer|analyst|scientist|architect|consultant|"
    r"manager|lead|associate|specialist|administrator|designer|tester|programmer|officer|executive|"
    r"coordinator|director|head|president|secretary|treasurer|volunteer|freelancer?|researcher|"
    r"fellow|assistant|technician|representative|member|sde|swe|qa|devops|full[\s-]?stack)\b",
    re.I,
)
# Matched at the END of a segment, so "Software Engineer" stays a title while
# "RKN Software Solutions Pvt Ltd" / "Paper Limited (TNPL)" read as companies.
COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:inc|corp|corporation|ltd|limited|llc|llp|pvt|private|gmbh|technologies|technology|tech|systems|"
    r"solutions|labs|services|software|consulting|consultancy|group|infotech|academy|networks?|"
    r"industries|enterprises?|global|international|company|co)\b\.?(?:\s*\([^)]*\))?\s*$",
    re.I,
)
LOCATION_WORDS = {
    "remote", "hybrid", "onsite", "on-site", "india", "usa", "uk", "us", "coimbatore", "chennai", "bengaluru",
    "bangalore", "mumbai", "delhi", "new delhi", "hyderabad", "pune", "kolkata", "noida", "gurgaon", "gurugram",
    "madurai", "trichy", "tiruchirappalli", "salem", "erode", "tiruppur", "tirupur", "karaikudi", "kochi",
    "trivandrum", "mysore", "mysuru", "ahmedabad", "jaipur", "london", "singapore", "dubai", "tamil nadu",
    "tn", "karnataka", "kerala", "maharashtra", "san francisco", "new york", "seattle", "austin", "toronto",
}
LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:inc|corp|corporation|ltd|limited|llc|llp|pvt|private|gmbh|technologies|solutions|infotech|"
    r"consulting|consultancy|industries|enterprises?)\b\.?(?:\s*\([^)]*\))?\s*$",
    re.I,
)
# "[Link]"-style tokens, or a bare link word standing alone as a header field.
LINK_TOKEN_RE = re.compile(
    r"\[[^\]]{0,20}\]|(?:(?<=\s)|^)(?:link|live(?:\s+demo)?|demo|github|source\s+code|repo|view)(?=\s*$|\s{2,}|\s*\|)",
    re.I,
)
STRONG_SEPARATOR_RE = re.compile(r"\s*\|\s*|\s{2,}|\s+[—–]\s+|\s+-\s+|\s+@\s+|\s+·\s+|\s+at\s+(?=[A-Z])")
CERT_ISSUERS = {
    "udemy", "coursera", "nptel", "edx", "cisco", "aws", "amazon", "amazon web services", "aws academy",
    "microsoft", "google", "ibm", "oracle", "nvidia", "infosys", "infosys springboard", "simplilearn",
    "great learning", "hackerrank", "hacker rank", "skillrack", "skill rack", "linkedin", "linkedin learning",
    "forage", "board infinity", "guvi", "meta", "cambridge", "salesforce", "red hat", "mongodb", "kaggle",
    "freecodecamp", "datacamp", "udacity", "swayam", "iit madras", "100xdevs", "scaler", "geeksforgeeks",
    "deeplearning.ai", "university", "tcs ion", "wipro", "accenture", "cognizant", "postman", "github",
}


def strip_bullet(line: str) -> tuple[str, bool]:
    match = BULLET_RE.match(line)
    if match:
        return line[match.end():].strip(), True
    return line.strip(), False


def split_dates(text: str) -> tuple[str, str | None, str | None, str | None, bool]:
    """Remove the date span from a header line; return (rest, span, start, end, is_current)."""
    matches = list(DATE_SPAN_RE.finditer(text))
    if not matches:
        return text.strip(), None, None, None, False
    # Prefer a range ("Jan 2024 – Present") over a lone year that may be part of a name.
    ranged = [m for m in matches if re.search(r"\s(?:-|–|—|to|until)\s|[-–—]", m.group(0).strip("()"))]
    chosen = ranged[-1] if ranged else matches[-1]
    span = chosen.group(0).strip().strip("()").strip()
    rest = (text[: chosen.start()] + " " + text[chosen.end():]).strip()
    rest = re.sub(r"\s*[|,·–—-]\s*$", "", rest).strip()
    rest = re.sub(r"^\s*[|,·–—-]\s*", "", rest).strip()
    parts = re.split(r"\s*(?:-|–|—|\bto\b|\buntil\b)\s*", span, maxsplit=1, flags=re.I)
    start = parts[0].strip() if parts and parts[0].strip() else None
    end = parts[1].strip() if len(parts) == 2 and parts[1].strip() else None
    is_current = bool(end and re.match(r"(?:present|current|now|till\s+date|to\s+date|ongoing)", end, re.I))
    return rest, span, start, end, is_current


def is_date_only(text: str) -> bool:
    rest, span, *_ = split_dates(text)
    return bool(span) and not re.sub(r"[\s|,·:–—()-]+", "", rest)


def is_description(text: str) -> bool:
    if not text.strip():
        return False
    if text[0].islower() or ACTION_VERB_RE.match(text):
        return True
    # Pipes and column gaps mark structured header fields ("Name | Stack  Dates").
    if "|" in text or re.search(r"\S\s{2,}\S", text):
        return False
    words = split_dates(text)[0].split()
    if len(words) >= 15:
        return True
    return text.rstrip().endswith(".") and len(words) >= 8


def split_segments(text: str) -> list[str]:
    return [seg.strip(" ,;:|·–—-") for seg in STRONG_SEPARATOR_RE.split(text) if seg and seg.strip(" ,;:|·–—-")]


def is_location(segment: str) -> bool:
    parts = [p.strip().casefold() for p in segment.split(",") if p.strip()]
    return bool(parts) and all(p in LOCATION_WORDS for p in parts)


def strip_location_tail(segment: str) -> tuple[str, str | None]:
    if "," in segment:
        head, tail = segment.split(",", 1)
        if is_location(tail):
            return head.strip(), tail.strip()
    return segment, None


_HEADINGS = {alias for aliases in (*SECTION_ALIASES.values(), *RESUME_EXTRA_SECTIONS.values()) for alias in aliases}


def is_section_heading(text: str) -> bool:
    return text.strip(" :-–—#*").casefold() in _HEADINGS


def section_lines(block: str) -> list[str]:
    """Non-empty lines of a section, minus any section heading carried into the block."""
    return [line.strip() for line in block.splitlines() if line.strip() and not is_section_heading(line)]


def looks_line_structured(block: str) -> bool:
    lines = section_lines(block)
    return len(lines) >= 2


class StructuredSectionParser:
    """Mixin used by ResumeExtractor; relies on its tech/degree helpers."""

    # ------------------------------------------------------------------ experience
    @classmethod
    def _parse_experience_header(cls, header: str) -> dict[str, Any]:
        rest, span, start, end, is_current = split_dates(header)
        rest = re.sub(r"(?i)^(?:company|organi[sz]ation|employer)\s*:\s*", "", rest).strip()
        title: str | None = None
        company: str | None = None
        location: str | None = None
        others: list[str] = []
        for segment in split_segments(rest):
            segment, tail_location = strip_location_tail(segment)
            location = location or tail_location
            if is_location(segment):
                location = location or segment
            elif title is None and ROLE_WORD_RE.search(segment) and not COMPANY_SUFFIX_RE.search(segment):
                title = segment
            else:
                others.append(segment)
        if others:
            # Legal-entity suffixes identify the employer; otherwise the employer is the last
            # field ("Engineer — AI/ML Systems — KCIRI": the middle field is a team/area).
            with_suffix = [seg for seg in others if LEGAL_SUFFIX_RE.search(seg)]
            company = with_suffix[0] if with_suffix else others[-1]
            if title is None and len(others) >= 2:
                title = others[0] if others[0] != company else None
        return {
            "title": title, "company": company, "location": location,
            "duration": span, "start_date": start, "end_date": end, "is_current": is_current,
        }

    @classmethod
    def _experience_structured(cls, block: str) -> list[dict[str, Any]]:
        lines = section_lines(block)
        if len(lines) < 2:
            return []
        entries: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        def open_entry(header: str) -> dict[str, Any]:
            entry = {"headers": [header], "bullets": [], "descriptions": [], "techs": [], "role": None, "dates": None}
            entries.append(entry)
            return entry

        for raw in lines:
            text, bullet = strip_bullet(raw)
            if not text:
                continue
            label = LABEL_RE.match(text)
            if bullet:
                if current is not None:
                    current["bullets"].append(text)
                continue
            if label:
                name = re.sub(r"\s+", " ", label.group("label")).casefold()
                value = label.group("value").strip()
                if current is None and name not in ROLE_LABELS:
                    continue
                if name in ROLE_LABELS:
                    current = current or open_entry("")
                    role_rest, role_span, *_ = split_dates(value)
                    current["role"] = (re.split(r"\s{2,}|\s*\|\s*", role_rest)[0] or role_rest).strip()
                    if role_span and not current["dates"]:
                        current["dates"] = role_span
                elif name in TECH_LABELS:
                    current["techs"].append(value)
                else:
                    current["descriptions"].append(text)
                continue
            if is_date_only(text):
                if current is not None and current["dates"] is None and not current["bullets"]:
                    current["dates"] = text
                elif current is None or current["bullets"] or current["descriptions"]:
                    current = open_entry("")
                    current["dates"] = text
                continue
            if is_description(text):
                if current is not None:
                    current["descriptions"].append(text)
                continue
            if current is not None and re.fullmatch(r"[A-Z][a-z]{1,7}\.?", text):
                continue  # clipped fragment of a wrapped field (e.g. "Coimba"), not a new entry
            # Header line: continue the current header block until its body starts.
            if (
                current is not None
                and not current["bullets"]
                and not current["descriptions"]
                and len([h for h in current["headers"] if h]) < 2
            ):
                current["headers"].append(text)
            else:
                current = open_entry(text)

        items: list[dict[str, Any]] = []
        for entry in entries:
            header_text = "  |  ".join(h for h in entry["headers"] if h)
            if entry["dates"]:
                header_text = f"{header_text}  {entry['dates']}" if header_text else entry["dates"]
            parsed = cls._parse_experience_header(header_text) if header_text else {}
            title = entry["role"] or parsed.get("title")
            company = parsed.get("company")
            if entry["role"] and not company and parsed.get("title"):
                company = parsed.get("title")
            if not title and not company:
                continue
            if company and title and company.casefold() == title.casefold():
                company = None
            responsibilities = entry["descriptions"] + entry["bullets"]
            # A stated length ("Three Months Internship") is kept as the duration text;
            # start/end dates still come from the date range.
            stated = TEXT_DURATION_RE.search(" ".join(entry["headers"]))
            duration = stated.group(0) if stated else parsed.get("duration")
            description = " ".join(responsibilities) or " ".join(filter(None, [company, title, duration]))
            employment_type = cls._detect_employment_type(None, f"{title or ''} {header_text}")
            items.append({
                "company": company[:255] if company else None,
                "designation": title[:255] if title else None,
                "title": title[:255] if title else None,
                "employment_type": employment_type,
                "start_date": parsed.get("start_date"),
                "end_date": parsed.get("end_date"),
                "is_current": bool(parsed.get("is_current")),
                "duration": duration,
                "description": description,
                "responsibilities": responsibilities,
                "location": parsed.get("location"),
            })
        return items

    # ------------------------------------------------------------------ projects
    @classmethod
    def _clean_project_name(cls, name: str) -> str:
        name = LINK_TOKEN_RE.sub("", name)
        name = re.sub(r"(?i)^(?:project\s*\d*\s*[:.\-–—]\s*)", "", name).strip()
        name = re.sub(r":\s*\(", " (", name)
        name = re.sub(r"\(\s*\)", "", name)
        return name.strip(" :|,-–—·").strip()

    @classmethod
    def _project_from_lines(cls, header: str, body: list[str], techs: list[str]) -> dict[str, Any] | None:
        rest, *_ = split_dates(header)
        rest = LINK_TOKEN_RE.sub("  ", rest)
        tech_part = ""
        if "|" in rest:
            name, tech_part = rest.split("|", 1)
        else:
            segments = [seg for seg in re.split(r"\s{2,}", rest) if seg.strip(" -–—|")]
            name = segments[0] if segments else rest
            if len(segments) > 1:
                tail = " ".join(segments[1:])
                if "," in tail or "·" in tail:
                    tech_part = tail
        name = cls._clean_project_name(name)
        description_from_name = ""
        colon = re.match(r"^(.{3,120}?):\s+(.{12,})$", name)
        if colon and len(colon.group(1).split()) <= 15:
            name, description_from_name = colon.group(1).strip(), colon.group(2).strip()
        if not name or len(name) < 2:
            return None
        body_text = " ".join(filter(None, [description_from_name, *body]))
        # The title often carries the key terms ("PLC-Based Boiler Automation"), so keep it
        # in the description that downstream matching reads as evidence.
        separator = " " if name.endswith((".", ":", "!", "?")) else ". "
        description = f"{name}{separator}{body_text}" if body_text else name
        # Re-label stack values so every listed item is taken, not just vocabulary terms.
        labelled = [f"Tech Stack: {value.strip()}" for value in (tech_part, *techs) if value and value.strip()]
        tech_source = "\n".join([*labelled, description])
        return {
            "name": name[:255],
            "description": description,
            "technologies": cls._extract_project_technologies(tech_source),
        }

    @staticmethod
    def _is_title_bullet(text: str) -> bool:
        """A bullet that names a project ("Project: X", "Name: what it does", "Name – tagline")."""
        if re.match(r"(?i)^project\s*\d*\s*[:.\-–—]", text):
            return True
        if ACTION_VERB_RE.match(text):
            return False
        prefix = re.match(r"^([^:]{3,100}?):\s", text)
        if prefix and len(prefix.group(1).split()) <= 12:
            return True
        return len(text.split()) <= 12 and not text.rstrip().endswith(".")

    @classmethod
    def _projects_structured(cls, block: str) -> list[dict[str, Any]]:
        lines = section_lines(block)
        if len(lines) < 2:
            return []
        classified: list[tuple[str, str]] = []  # (role, text)
        for raw in lines:
            text, bullet = strip_bullet(raw)
            if not text:
                continue
            label = LABEL_RE.match(text)
            if label and re.sub(r"\s+", " ", label.group("label")).casefold() in TECH_LABELS:
                classified.append(("tech", label.group("value")))
            elif bullet:
                classified.append(("bullet", text))
            elif re.match(r"(?i)^project\s*\d*\s*[:.\-–—]\s*\S", text):
                classified.append(("header", text))
            elif is_date_only(text):
                classified.append(("date", text))
            elif is_description(text):
                classified.append(("desc", text))
            else:
                classified.append(("header", text))

        headers = [t for role, t in classified if role == "header"]
        bullets = [t for role, t in classified if role == "bullet"]
        bullet_titled = not headers and any(cls._is_title_bullet(b) for b in bullets)
        if not bullet_titled and headers and bullets:
            # "• Project: Name" / "• Name: description" bullets act as titles when the
            # non-bullet "headers" are only wrapped title continuations.
            bullet_titled = all(re.match(r"(?i)^project\s*\d*\s*[:.]", b) for b in bullets)

        projects: list[dict[str, Any]] = []
        header: str | None = None
        body: list[str] = []
        techs: list[str] = []

        def flush() -> None:
            if header is not None:
                project = cls._project_from_lines(header, body, techs)
                if project:
                    projects.append(project)

        for role, text in classified:
            if bullet_titled:
                starts_project = role == "bullet" and cls._is_title_bullet(text)
            else:
                starts_project = role == "header"
            if bullet_titled and header is not None and not body and ":" not in header:
                if role == "header":
                    header = f"{header} {text}"  # wrapped title continuation
                    continue
                wrapped_title = re.match(r"^([^:]{3,80}?):\s+(\S.*)$", text)
                if role == "desc" and wrapped_title and len(wrapped_title.group(1).split()) <= 8:
                    # "• Long Project Title ... Farm" / "Decision Support System: Built ..."
                    header = f"{header} {wrapped_title.group(1).strip()}"
                    body.append(wrapped_title.group(2).strip())
                    continue
            if starts_project:
                flush()
                header, body, techs = text, [], []
            elif header is None:
                continue
            elif role == "tech":
                techs.append(text)
            elif role == "date":
                continue
            else:
                body.append(text)
        flush()

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for project in projects:
            key = project["name"].casefold()
            if key not in seen:
                seen.add(key)
                deduped.append(project)
        return deduped

    # ------------------------------------------------------------------ education
    @classmethod
    def _education_line_features(cls, line: str) -> dict[str, Any]:
        degree = None
        for pattern, canonical in cls.DEGREE_EXTRACTION_PATTERNS:
            if re.search(pattern, line, re.I):
                degree = canonical
                break
        institution = None
        for segment in split_segments(line):
            segment, _ = strip_location_tail(segment)
            # "Secondary School Leaving Certificate" is a degree, not an institution:
            # judge the segment with its degree wording removed.
            without_degree = segment
            for pattern, _canonical in cls.DEGREE_EXTRACTION_PATTERNS:
                without_degree = re.sub(pattern, " ", without_degree, flags=re.I)
            without_degree = re.sub(r"\((?:[A-Z]{2,5})?\)", " ", without_degree)
            without_degree = re.sub(r"\s+", " ", without_degree).strip(" -–—,()")
            for pattern in cls.INSTITUTION_EXTRACTION_PATTERNS:
                match = re.search(pattern, without_degree, re.I)
                if match:
                    candidate = cls._clean_institution_name(without_degree) or cls._clean_institution_name(match.group(0))
                    if candidate and (len(candidate.split()) >= 2 or candidate.isupper()):
                        institution = candidate
                    break
            if institution:
                break
        field = None
        if degree not in {"Higher Secondary (12th)", "Secondary School (10th)"}:
            for pattern, canonical in cls.FIELD_EXTRACTION_PATTERNS:
                if re.search(pattern, line, re.I):
                    field = canonical
                    break
        years = _YEAR_RE.findall(line)
        year = f"{years[0]}-{years[-1]}" if len(years) >= 2 and years[0] != years[-1] else (years[0] if years else None)
        grade_match = cls.GRADE_PATTERN.search(line)
        return {
            "degree": degree, "institution": institution, "field_of_study": field,
            "year": year, "grade": grade_match.group(0) if grade_match else None,
        }

    @classmethod
    def _education_structured(cls, block: str) -> list[dict[str, str | None]]:
        lines = [strip_bullet(line)[0] for line in section_lines(block)]
        lines = [line for line in lines if line]
        if len(lines) < 2:
            return []
        entries: list[dict[str, str | None]] = []
        current: dict[str, str | None] | None = None
        for line in lines:
            feats = cls._education_line_features(line)
            if not any(feats.values()):
                continue
            starts_new = current is None or (
                (feats["degree"] and current.get("degree"))
                or (feats["institution"] and current.get("institution"))
                or (feats["year"] and current.get("year") and not feats["degree"] and not feats["institution"]
                    and is_date_only(line) and (current.get("degree") or current.get("institution")))
            )
            if starts_new:
                current = {"degree": None, "institution": None, "year": None, "field_of_study": None, "grade": None}
                entries.append(current)
            for key, value in feats.items():
                if value and not current.get(key):
                    current[key] = value
        return [entry for entry in entries if entry.get("degree") or entry.get("institution")]

    # ------------------------------------------------------------------ certifications
    @classmethod
    def _certifications_structured(cls, block: str) -> list[str]:
        lines = section_lines(block)
        if len(lines) < 2 and not any(sep in block for sep in ("|", "  ", " · ")):
            return []
        certs: list[str] = []
        for raw in lines:
            text, _ = strip_bullet(raw)
            if not text:
                continue
            if re.match(r"(?i)^(?:issued|credential|validity|valid\s+until|expires?|certificate\s+(?:id|no)|id\s*:)", text):
                continue
            if re.match(r"(?i)^(?:https?://|www\.)", text):
                continue
            rest = text
            for _ in range(3):
                stripped, span, *_ = split_dates(rest)
                if not span:
                    break
                rest = stripped
            rest = re.sub(r"(?i)\b(?:issued|completed|credential\s+id)\b.*$", "", rest).strip()
            rest = cls._clean_cert_text(rest) or ""
            current: str | None = None
            issuer: str | None = None
            segments: list[str] = []
            # Dashes are part of many certificate names ("SQL - Basics"), so only pipes,
            # column gaps and middle dots separate fields; a dash may only split off an issuer.
            for segment in re.split(r"\s*\|\s*|\s{2,}|\s+·\s+", rest):
                segment = segment.strip(" ,;:-–—")
                if re.fullmatch(r"\(.*\)", segment):
                    segment = segment[1:-1].strip()
                if not re.search(r"\w", segment):
                    continue
                dash = re.match(r"^(.+?)\s+[-–—]\s+([^-–—]+)$", segment)
                if dash and cls._looks_like_issuer(dash.group(2).strip()):
                    segments.extend([dash.group(1).strip(), dash.group(2).strip()])
                else:
                    segments.append(segment)
            for segment in segments:
                if current is not None and cls._looks_like_issuer(segment):
                    issuer = issuer or segment
                    continue
                if current is not None:
                    certs.append(cls._format_cert(current, issuer))
                current, issuer = segment, None
            if current:
                certs.append(cls._format_cert(current, issuer))
        deduped: list[str] = []
        seen: set[str] = set()
        for cert in cls._merge_wrapped_certs(certs):
            key = cert.casefold()
            if len(cert) >= 3 and key not in seen:
                seen.add(key)
                deduped.append(cert[:255])
        return deduped

    @staticmethod
    def _looks_like_issuer(segment: str) -> bool:
        key = segment.casefold().strip(" .")
        if key in CERT_ISSUERS or any(key.startswith(issuer + " ") for issuer in CERT_ISSUERS):
            return True
        words = segment.split()
        cert_words = re.search(r"(?i)\b(?:certified|certificat\w*|fundamentals|foundations?|programming|course|essentials|developer|practitioner|associate|professional|basics?|introduction|mastering|learn)\b", segment)
        return len(words) <= 3 and not cert_words and (segment.isupper() or all(w[:1].isupper() for w in words if w[:1].isalpha()))

    @staticmethod
    def _format_cert(name: str, issuer: str | None) -> str:
        name = re.sub(r"\s+", " ", name).strip(" -–—:|")
        if issuer and issuer.casefold() not in name.casefold():
            return f"{name} ({issuer.strip()})"
        return name
