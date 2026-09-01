import re
from typing import Any

from app.services.pipeline.canonical_dictionaries import (
    CERTIFICATION_ALIASES, DEGREE_ALIASES, LANGUAGE_ALIASES, LOCATION_ALIASES,
    RULESET_VERSION, SKILL_ALIASES, TITLE_ALIASES,
)
from app.services.pipeline.normalization_rules import (
    NormalizationAudit, canonicalize, clean_text, duration_between, format_duration,
    normalize_company, normalize_date, normalize_list, normalize_phone, stable_unique,
)


class ResumeNormalizer:
    def normalize(self, extracted: Any) -> dict[str, Any]:
        audit = NormalizationAudit()
        skills = normalize_list(list(extracted.skills or []), SKILL_ALIASES, "skills", audit)
        education = [self._education(item, audit) for item in (extracted.education or [])]
        experience = [self._experience(item, audit) for item in (extracted.experience or [])]
        companies = [company for value in (extracted.companies or []) if (company := normalize_company(value, audit))]
        companies.extend(item["company"] for item in experience if item["company"])
        designation = canonicalize(extracted.designation, TITLE_ALIASES, "job_titles", audit)
        job_titles = ([designation] if designation else []) + [item["job_title"] for item in experience if item["job_title"]]
        location = self._location(extracted.location, audit)
        raw_projects = getattr(extracted, "projects", None) or []
        projects = []
        for item in raw_projects:
            p_dict = {
                "name": item.get("name") if isinstance(item, dict) else getattr(item, "name", None),
                "description": item.get("description") if isinstance(item, dict) else getattr(item, "description", None),
                "technologies": normalize_list(
                    list((item.get("technologies") if isinstance(item, dict) else getattr(item, "technologies", None)) or []),
                    SKILL_ALIASES, "skills", audit
                ),
            }
            for field in ("deliverables", "highlights", "summary", "responsibilities", "outcomes", "details"):
                val = item.get(field) if isinstance(item, dict) else getattr(item, field, None)
                if val:
                    p_dict[field] = val
            projects.append(p_dict)
        return {
            "skills": skills,
            "education": education,
            "companies": stable_unique(companies),
            "job_titles": stable_unique(job_titles),
            "experience": experience,
            "projects": projects,
            "phone": normalize_phone(getattr(extracted, "phone", None) or (extracted.get("phone") if isinstance(extracted, dict) else None), audit),
            "email": self._email(getattr(extracted, "email", None) or (extracted.get("email") if isinstance(extracted, dict) else None), audit),
            "locations": [location] if location else [],
            "languages": normalize_list(list(extracted.languages or []), LANGUAGE_ALIASES, "languages", audit),
            "certifications": normalize_list(list(extracted.certifications or []), CERTIFICATION_ALIASES, "certifications", audit),
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
        def get_v(key: str) -> Any:
            return item.get(key) if isinstance(item, dict) else getattr(item, key, None)
        date, _ = normalize_date(get_v("year"), "education.graduation_date", audit)
        return {
            "degree": canonicalize(get_v("degree"), DEGREE_ALIASES, "education.degree", audit),
            "field_of_study": clean_text(get_v("field_of_study")) if get_v("field_of_study") else None,
            "institution": clean_text(get_v("institution")) if get_v("institution") else None,
            "graduation_date": date,
        }

    @staticmethod
    def _experience(item: Any, audit: NormalizationAudit) -> dict[str, Any]:
        def get_v(key: str) -> Any:
            return item.get(key) if isinstance(item, dict) else getattr(item, key, None)
        start_source = get_v("start_date")
        end_source = get_v("end_date")

        if not start_source and not end_source:
            duration = clean_text(get_v("duration") or "")
            parts = re.split(r"\s+(?:-|–|—|to)\s+", duration, maxsplit=1, flags=re.I) if duration else []
            start_source = parts[0] if parts else None
            end_source = parts[1] if len(parts) == 2 else None

        start, _ = normalize_date(start_source, "experience.start_date", audit)
        end, current = normalize_date(end_source, "experience.end_date", audit)
        if get_v("is_current") is True:
            current = True
        months = duration_between(start, end, current)
        company = normalize_company(get_v("company"), audit)
        title = canonicalize(get_v("title") or get_v("designation"), TITLE_ALIASES, "job_titles", audit)
        
        description = get_v("description")
        responsibilities = get_v("responsibilities") or []
        employment_type = get_v("employment_type") or "Full-time"
        location = get_v("location")

        return {
            "company": company,
            "job_title": title,
            "employment_type": employment_type,
            "start_date": start,
            "end_date": end,
            "is_current": current,
            "duration_months": months,
            "duration_display": format_duration(months),
            "description": description,
            "responsibilities": responsibilities,
            "location": location,
        }

