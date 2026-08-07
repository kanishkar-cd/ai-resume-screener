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
        skills = normalize_list(list(extracted.skills or []), SKILL_ALIASES, "skills", audit)
        degrees = normalize_list(list(extracted.education or []), DEGREE_ALIASES, "degree_requirements", audit)
        requirements = [parsed for value in (extracted.experience or []) if (parsed := parse_experience_requirement(value, audit))]
        domain = canonicalize(extracted.domain, DOMAIN_ALIASES, "domain", audit)
        keyword_aliases = {**SKILL_ALIASES, **TITLE_ALIASES, **DOMAIN_ALIASES}
        keywords = normalize_list(list(extracted.keywords or []), keyword_aliases, "keywords", audit)
        return {
            "skills": skills,
            "degree_requirements": degrees,
            "experience_requirements": requirements,
            "domain": domain,
            "keywords": stable_unique(keywords),
            "normalization_metadata": audit.metadata(),
            "ruleset_version": RULESET_VERSION,
        }
