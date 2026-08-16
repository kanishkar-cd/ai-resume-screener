import re
from typing import Any

from app.services.pipeline.canonical_dictionaries import (
    CERTIFICATION_ALIASES, DEGREE_ALIASES, LANGUAGE_ALIASES, LOCATION_ALIASES,
    RULESET_VERSION, SKILL_ALIASES, TITLE_ALIASES,
)
from app.services.pipeline.normalization_rules import (
    NormalizationAudit, canonicalize, clean_text, duration_between, format_duration,
    merge_experience_intervals, normalize_company, normalize_date, normalize_list, normalize_phone, stable_unique,
)


class ResumeNormalizer:
    def normalize(self, extracted: Any) -> dict[str, Any]:
        audit = NormalizationAudit()
        skills = normalize_list(list(getattr(extracted, "skills", None) or []), SKILL_ALIASES, "skills", audit)

        raw_certs = [str(c) for c in (getattr(extracted, "certifications", None) or [])]
        clean_edu = []
        for item in (getattr(extracted, "education", None) or []):
            obj = item if isinstance(item, dict) else (getattr(item, "__dict__", {}) or {})
            deg = str(obj.get("degree") or "")
            inst = str(obj.get("institution") or "")
            field = str(obj.get("field_of_study") or "")
            combined = f"{deg} {inst} {field}".casefold()
            is_cert = any(kw in combined for kw in ("certification", "certificate", "fundamentals", "coursera", "udemy", "online certification", "springboard", "skillrack", "infosys", "exam", "bootcamp"))
            has_academic_degree = any(deg_alias in deg.casefold() for deg_alias in DEGREE_ALIASES) or any(deg_term in combined for deg_term in ("b.tech", "btech", "b.e.", "be", "bachelor", "master", "m.tech", "mtech", "m.e.", "me", "b.sc", "bsc", "m.sc", "msc", "phd", "ph.d", "diploma", "degree"))
            if is_cert and not has_academic_degree:
                cert_title = f"{deg} - {inst}".strip(" -") if deg and inst else (deg or inst or field)
                if cert_title and cert_title not in raw_certs:
                    raw_certs.append(cert_title)
            else:
                clean_edu.append(item)

        education = [self._education(item, audit) for item in clean_edu]
        experience = [self._experience(item, audit) for item in (getattr(extracted, "experience", None) or [])]
        projects = [self._project(item, audit) for item in (getattr(extracted, "projects", None) or [])]
        companies = [company for value in (getattr(extracted, "companies", None) or []) if (company := normalize_company(value, audit))]
        companies.extend(item["company"] for item in experience if item.get("company"))
        designation = canonicalize(getattr(extracted, "designation", None), TITLE_ALIASES, "job_titles", audit)
        job_titles = ([designation] if designation else []) + [item["job_title"] for item in experience if item.get("job_title")]
        location = self._location(getattr(extracted, "location", None), audit)

        total_experience_months = merge_experience_intervals(experience)
        candidate_level = "FRESHER" if total_experience_months <= 12 else "EXPERIENCED"
        certifications = normalize_list(raw_certs, CERTIFICATION_ALIASES, "certifications", audit)

        return {
            "skills": skills,
            "education": education,
            "companies": stable_unique(companies),
            "job_titles": stable_unique(job_titles),
            "experience": experience,
            "projects": projects,
            "total_experience_months": total_experience_months,
            "candidate_level": candidate_level,
            "phone": normalize_phone(getattr(extracted, "phone", None), audit),
            "email": self._email(getattr(extracted, "email", None), audit),
            "locations": [location] if location else [],
            "languages": normalize_list(list(getattr(extracted, "languages", None) or []), LANGUAGE_ALIASES, "languages", audit),
            "certifications": certifications,
            "normalization_metadata": audit.metadata(),
            "ruleset_version": RULESET_VERSION,
        }

    @staticmethod
    def _email(value: str | None, audit: NormalizationAudit) -> str | None:
        if not value:
            return None
        source = clean_text(value)
        canonical = source.lower()
        audit.record("email", source, canonical, "email_lowercase", 1.0)
        return canonical

    @staticmethod
    def _location(value: str | None, audit: NormalizationAudit) -> dict[str, str | None] | None:
        if not value:
            return None
        source = clean_text(value)
        canonical = LOCATION_ALIASES.get(source.casefold())
        if canonical:
            audit.record("locations", source, canonical["display_name"], "location_alias", 1.0)
            return dict(canonical)

        # Heuristic parsing for unknown location strings: "City, Region, Country"
        parts = [p.strip() for p in source.split(",") if p.strip()]
        city, region, country = None, None, None
        if len(parts) == 1:
            city = parts[0]
        elif len(parts) == 2:
            city, region = parts[0], parts[1]
        elif len(parts) >= 3:
            city, region, country = parts[0], parts[1], parts[2]

        COUNTRY_MAP = {
            "india": "IN", "in": "IN",
            "united states": "US", "usa": "US", "us": "US",
            "united kingdom": "GB", "uk": "GB", "great britain": "GB",
            "canada": "CA", "ca": "CA",
            "australia": "AU", "au": "AU",
            "germany": "DE", "de": "DE",
        }

        country_code = None
        if country:
            country_code = COUNTRY_MAP.get(country.casefold())
        elif city and city.casefold() in COUNTRY_MAP:
            country_code = COUNTRY_MAP.get(city.casefold())
            country = city
            city = None
        elif region and region.casefold() in COUNTRY_MAP:
            country_code = COUNTRY_MAP.get(region.casefold())
            country = region
            region = None

        audit.record("locations", source, source, "preserved_unknown", 1.0)
        return {
            "city": city,
            "region": region,
            "country": country,
            "country_code": country_code,
            "display_name": source,
        }

    @staticmethod
    def _education(item: Any, audit: NormalizationAudit) -> dict[str, str | None]:
        obj = item if isinstance(item, dict) else (getattr(item, "__dict__", {}) or {})
        date, _ = normalize_date(obj.get("year"), "education.graduation_date", audit)
        return {
            "degree": canonicalize(obj.get("degree"), DEGREE_ALIASES, "education.degree", audit),
            "field_of_study": clean_text(obj["field_of_study"]) if obj.get("field_of_study") else None,
            "institution": clean_text(obj["institution"]) if obj.get("institution") else None,
            "graduation_date": date,
        }

    @staticmethod
    def _project(item: Any, audit: NormalizationAudit) -> dict[str, Any]:
        obj = item if isinstance(item, dict) else (getattr(item, "__dict__", {}) or {})
        name = clean_text(str(obj.get("name"))) if obj.get("name") else None
        raw_tech = list(obj.get("technologies") or [])
        technologies = normalize_list(raw_tech, SKILL_ALIASES, "project.technologies", audit)
        desc = obj.get("description")
        description = clean_text(str(desc)) if desc else None
        return {
            "name": name,
            "technologies": technologies,
            "description": description,
        }

    @staticmethod
    def _experience(item: Any, audit: NormalizationAudit) -> dict[str, Any]:
        obj = item if isinstance(item, dict) else (getattr(item, "__dict__", {}) or {})
        start_source = obj.get("start_date")
        end_source = obj.get("end_date")

        if not start_source and not end_source:
            duration = clean_text(str(obj.get("duration") or ""))
            parts = re.split(r"\s+(?:-|–|—|to)\s+", duration, maxsplit=1, flags=re.I) if duration else []
            start_source = parts[0] if parts else None
            end_source = parts[1] if len(parts) == 2 else None

        start, _ = normalize_date(start_source, "experience.start_date", audit)
        end, current = normalize_date(end_source, "experience.end_date", audit)
        months = duration_between(start, end, current)
        if months is None and obj.get("duration_months"):
            try:
                months = int(obj["duration_months"])
            except (ValueError, TypeError):
                months = None
        if months is None:
            desc_text = str(obj.get("description") or "")
            dur_text = str(obj.get("duration") or "")
            from app.services.pipeline.normalization_rules import parse_duration_months
            months = parse_duration_months(desc_text) or parse_duration_months(dur_text)
        company = normalize_company(obj.get("company"), audit)
        title = canonicalize(obj.get("title") or obj.get("designation"), TITLE_ALIASES, "job_titles", audit)

        raw_resp = list(obj.get("responsibilities") or [])
        responsibilities = [clean_text(str(r)) for r in raw_resp if clean_text(str(r))]
        desc_val = obj.get("description")
        description = clean_text(str(desc_val)) if desc_val else None

        return {
            "company": company, "job_title": title, "start_date": start,
            "end_date": end, "is_current": current, "duration_months": months,
            "duration_display": format_duration(months),
            "description": description,
            "responsibilities": responsibilities,
        }

