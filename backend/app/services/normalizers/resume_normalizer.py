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
        return {
            "skills": skills,
            "education": education,
            "companies": stable_unique(companies),
            "job_titles": stable_unique(job_titles),
            "experience": experience,
            "phone": normalize_phone(extracted.phone, audit),
            "email": self._email(extracted.email, audit),
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
    def _education(item: dict[str, Any], audit: NormalizationAudit) -> dict[str, str | None]:
        date, _ = normalize_date(item.get("year"), "education.graduation_date", audit)
        return {
            "degree": canonicalize(item.get("degree"), DEGREE_ALIASES, "education.degree", audit),
            "field_of_study": clean_text(item["field_of_study"]) if item.get("field_of_study") else None,
            "institution": clean_text(item["institution"]) if item.get("institution") else None,
            "graduation_date": date,
        }

    @staticmethod
    def _experience(item: dict[str, Any], audit: NormalizationAudit) -> dict[str, Any]:
        start_source = item.get("start_date")
        end_source = item.get("end_date")

        if not start_source and not end_source:
            duration = clean_text(item.get("duration") or "")
            parts = re.split(r"\s+(?:-|–|—|to)\s+", duration, maxsplit=1, flags=re.I) if duration else []
            start_source = parts[0] if parts else None
            end_source = parts[1] if len(parts) == 2 else None

        start, _ = normalize_date(start_source, "experience.start_date", audit)
        end, current = normalize_date(end_source, "experience.end_date", audit)
        months = duration_between(start, end, current)
        company = normalize_company(item.get("company"), audit)
        title = canonicalize(item.get("title") or item.get("designation"), TITLE_ALIASES, "job_titles", audit)
        return {
            "company": company, "job_title": title, "start_date": start,
            "end_date": end, "is_current": current, "duration_months": months,
            "duration_display": format_duration(months),
        }

