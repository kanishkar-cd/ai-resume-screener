from typing import Any


class ConfidenceService:
    FIELDS = ("candidate_name", "email", "phone", "designation", "location", "skills", "education", "experience", "projects", "certifications", "companies", "languages")

    @classmethod
    def calculate(cls, extracted_resume: Any) -> float:
        populated = sum(getattr(extracted_resume, field, None) not in (None, "", []) for field in cls.FIELDS)
        return round(populated / len(cls.FIELDS) * 100, 2)
