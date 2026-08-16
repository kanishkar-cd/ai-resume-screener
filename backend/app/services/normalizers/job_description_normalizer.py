from typing import Any

from app.services.pipeline.canonical_dictionaries import (
    DEGREE_ALIASES, DOMAIN_ALIASES, RULESET_VERSION, SKILL_ALIASES, TITLE_ALIASES,
)
from app.services.pipeline.normalization_rules import (
    NormalizationAudit, canonicalize, normalize_list, parse_experience_requirement,
    stable_unique,
)


class JobDescriptionNormalizer:
    def normalize(self, extracted: Any) -> dict[str, Any]:
        audit = NormalizationAudit()
        skills = normalize_list(list(getattr(extracted, "skills", None) or []), SKILL_ALIASES, "skills", audit)
        req_skills = list(getattr(extracted, "required_skills", None) or [])
        pref_skills = list(getattr(extracted, "preferred_skills", None) or [])

        normalized_req = normalize_list(req_skills, SKILL_ALIASES, "required_skills", audit)
        normalized_pref = normalize_list(pref_skills, SKILL_ALIASES, "preferred_skills", audit)

        # Enforce strict non-overlapping separation: preferred cannot contain required
        req_keys = {s.casefold() for s in normalized_req}
        normalized_pref = [s for s in normalized_pref if s.casefold() not in req_keys]

        degrees = normalize_list(list(getattr(extracted, "education", None) or []), DEGREE_ALIASES, "degree_requirements", audit)
        requirements = [parsed for value in (getattr(extracted, "experience", None) or []) if (parsed := parse_experience_requirement(value, audit))]
        domain = canonicalize(getattr(extracted, "domain", None), DOMAIN_ALIASES, "domain", audit)
        keyword_aliases = {**SKILL_ALIASES, **TITLE_ALIASES, **DOMAIN_ALIASES}
        keywords = normalize_list(list(getattr(extracted, "keywords", None) or []), keyword_aliases, "keywords", audit)
        return {
            "skills": skills,
            "job_title": getattr(extracted, "job_title", None),
            "required_skills": normalized_req,
            "preferred_skills": normalized_pref,
            "degree_requirements": degrees,
            "education_disciplines": list(getattr(extracted, "education_disciplines", None) or []),
            "experience_requirements": requirements,
            "responsibilities": list(getattr(extracted, "responsibilities", None) or []),
            "certifications": list(getattr(extracted, "certifications", None) or []),
            "domain": domain,
            "keywords": stable_unique(keywords),
            "normalization_metadata": audit.metadata(),
            "ruleset_version": RULESET_VERSION,
        }
