"""
JD Requirement Importance Classifier
Classifies how critical each requirement is to the role using LLM analysis of the JD context.
"""
from __future__ import annotations

import json
from typing import Any
import httpx
from pydantic import BaseModel, Field
import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class RequirementClassification(BaseModel):
    requirement_text: str
    importance: str = "important"  # "critical" | "important" | "minor"
    reasoning: str = ""
    is_likely_boilerplate: bool = False


class JDClassificationBatch(BaseModel):
    classifications: list[RequirementClassification] = Field(default_factory=list)


class JDRequirementImportanceClassifier:
    """Classifies how critical each requirement is based on JD language and context."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def classify(
        self, jd_text: str, requirements_list: list[str]
    ) -> dict[str, RequirementClassification]:
        if not requirements_list:
            return {}

        prompt_system = (
            "You are analyzing a job description to classify how critical each requirement is to the role. "
            "This will be used to weight candidate scoring, so be precise — do not default everything to 'critical.'\n\n"
            "For EACH requirement, classify its importance based on the LANGUAGE AND CONTEXT in the JD itself — "
            "not on how common or well-known the skill is.\n\n"
            "Use these signals:\n"
            "- 'critical': Language like 'required,' 'must have,' 'essential,' listed under a 'Requirements' or 'Must-Have' heading, "
            "or it's clearly a core function mentioned in the job title/summary.\n"
            "- 'important': Listed as a standard requirement but not emphasized, or appears in the main responsibilities without 'must-have' framing, "
            "or is one of several similar items in a list (no single one is indispensable).\n"
            "- 'minor': Language like 'nice to have,' 'preferred,' 'a plus,' 'bonus,' listed under a 'Preferred Qualifications' heading, "
            "or it's a generic/boilerplate item (e.g. 'good communication skills,' 'team player') that doesn't differentiate candidates.\n\n"
            "Also flag if a requirement appears to be template/boilerplate language unlikely to reflect genuine role-specific need "
            "(common in copy-pasted JDs) — this should lower its importance regardless of phrasing.\n\n"
            "Output ONLY valid JSON, no preamble:\n\n"
            "{\n"
            "  \"classifications\": [\n"
            "    {\n"
            "      \"requirement_text\": \"...\",\n"
            "      \"importance\": \"critical|important|minor\",\n"
            "      \"reasoning\": \"1 sentence citing the specific JD language or heading that signals this\",\n"
            "      \"is_likely_boilerplate\": true\n"
            "    }\n"
            "  ]\n"
            "}"
        )

        user_content = (
            f"JOB DESCRIPTION:\n{jd_text[:8000]}\n\n"
            f"EXTRACTED REQUIREMENTS (skills and responsibilities already parsed):\n"
            f"{json.dumps(requirements_list, indent=2)}"
        )

        payload = {
            "model": self.settings.GROQ_MODEL,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
        }

        # Try Groq, with fallback to Cerebras or rule-based fallback
        try:
            if self.settings.GROQ_API_KEY:
                async with httpx.AsyncClient(timeout=getattr(self.settings, "GROQ_TIMEOUT_SECONDS", 15.0)) as client:
                    resp = await client.post(
                        f"{self.settings.GROQ_BASE_URL.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {self.settings.GROQ_API_KEY}"},
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()["choices"][0]["message"]["content"]
                    parsed = JDClassificationBatch.model_validate(json.loads(data) if isinstance(data, str) else data)
                    return {c.requirement_text.strip().casefold(): c for c in parsed.classifications}
        except Exception as exc:
            logger.warning("jd_classification_groq_failed", error=str(exc))

        # Cerebras fallback
        cerebras_key = getattr(self.settings, "CEREBRAS_API_KEY", None)
        if cerebras_key:
            try:
                payload["model"] = getattr(self.settings, "CEREBRAS_MODEL", "gpt-oss-120b")
                url = f"{getattr(self.settings, 'CEREBRAS_BASE_URL', 'https://api.cerebras.ai/v1').rstrip('/')}/chat/completions"
                headers = {"Authorization": f"Bearer {cerebras_key}"}
                async with httpx.AsyncClient(timeout=getattr(self.settings, "CEREBRAS_TIMEOUT_SECONDS", 15.0)) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()["choices"][0]["message"]["content"]
                    parsed = JDClassificationBatch.model_validate(json.loads(data) if isinstance(data, str) else data)
                    return {c.requirement_text.strip().casefold(): c for c in parsed.classifications}
            except Exception as exc:
                logger.warning("jd_classification_cerebras_failed", error=str(exc))

        # Heuristic fallback if LLMs fail/offline
        results = {}
        for req in requirements_list:
            req_cf = req.casefold()
            is_boilerplate = any(w in req_cf for w in ("communication", "team player", "interpersonal", "fast learner", "collaborative", "enthusiastic"))
            if is_boilerplate:
                imp = "minor"
                reason = "Generic interpersonal or boilerplate phrasing."
            else:
                imp = "important"
                reason = "Standard parsed requirement."
            results[req_cf] = RequirementClassification(
                requirement_text=req,
                importance=imp,
                reasoning=reason,
                is_likely_boilerplate=is_boilerplate,
            )
        return results
