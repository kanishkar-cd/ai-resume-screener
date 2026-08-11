import json
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings


class AIJDExtraction(BaseModel):
    job_title: str | None = None
    domain: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    education_disciplines: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class AIJDExtractor:
    """Optional one-shot recovery for important JD fields missed by rules."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def extract(self, text: str) -> dict[str, Any] | None:
        if not self.settings.ENABLE_AI_JD_EXTRACTION or not self.settings.GROQ_API_KEY:
            return None
        payload = {
            "model": self.settings.GROQ_MODEL,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "Recover only facts explicitly present in this job description. Preserve required versus preferred skills and separate list items. Return JSON only; never invent requirements."},
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_schema", "json_schema": {"name": "jd_extraction", "strict": True, "schema": AIJDExtraction.model_json_schema()}},
        }
        async with httpx.AsyncClient(timeout=self.settings.AI_EXTRACTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.settings.GROQ_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.GROQ_API_KEY}"},
                json=payload,
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return AIJDExtraction.model_validate(json.loads(content) if isinstance(content, str) else content).model_dump()
