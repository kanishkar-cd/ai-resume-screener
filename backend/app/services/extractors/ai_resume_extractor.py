import json
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.schemas.extracted_info import EducationItem, ExperienceItem, ProjectItem


class AIResumeExtraction(BaseModel):
    """Internal structured output matching the existing extracted-resume contract."""

    candidate_name: str | None = None
    email: str | None = None
    phone: str | None = None
    designation: str | None = None
    location: str | None = None
    skills: list[str] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class AIResumeExtractor:
    """One-shot, optional resume recovery using Groq's OpenAI-compatible API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.ENABLE_AI_RESUME_EXTRACTION and bool(self.settings.GROQ_API_KEY)

    async def extract(self, resume_text: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        schema = AIResumeExtraction.model_json_schema()
        payload = {
            "model": self.settings.GROQ_MODEL,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract only facts explicitly supported by the resume. Return the requested JSON only. "
                        "Recover structured employment, education, and distinct projects from imperfect layouts. "
                        "Correct OCR variants only when context supports the correction; never invent facts."
                    ),
                },
                {"role": "user", "content": resume_text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "resume_extraction", "strict": True, "schema": schema},
            },
        }
        headers = {"Authorization": f"Bearer {self.settings.GROQ_API_KEY}"}
        async with httpx.AsyncClient(timeout=self.settings.AI_EXTRACTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.settings.GROQ_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
        return AIResumeExtraction.model_validate(parsed).model_dump()
