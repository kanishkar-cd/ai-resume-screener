from typing import Any
from uuid import uuid4
import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException

logger = structlog.get_logger(__name__)


class CDRecruitException(AppException):
    status_code = 502
    error_code = "CD_RECRUIT_INTEGRATION_FAILED"
    default_message = "CD-Recruit integration service call failed."


class CDRecruitService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_candidates(
        self,
        department_code: str,
        level: str,
        requisition_ref: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        base_url = self.settings.CD_RECRUIT_BASE_URL.rstrip("/")
        url = f"{base_url}/api/v1/partner/candidates"
        api_key = self.settings.CD_RECRUIT_API_KEY or ""

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "Idempotency-Key": str(uuid4()),
        }

        dept_code = department_code or self.settings.CD_RECRUIT_DEFAULT_DEPARTMENT_CODE
        target_level = level or self.settings.CD_RECRUIT_DEFAULT_LEVEL

        payload_candidates = []
        for candidate in candidates:
            payload_candidates.append({
                "name": candidate.get("candidate_name") or candidate.get("name", "Candidate"),
                "email": candidate.get("email", ""),
                "phone": candidate.get("phone", ""),
                "ai_score": candidate.get("ai_score", 0.0),
                "metadata": candidate.get("metadata", {}),
            })

        payload = {
            "department_code": dept_code,
            "level": target_level,
            "requisition_ref": requisition_ref,
            "candidates": payload_candidates,
        }

        logger.info(
            "[CD-RECRUIT] sending candidate handoff",
            url=url,
            requisition_ref=requisition_ref,
            department_code=dept_code,
            level=target_level,
            candidate_count=len(payload_candidates),
        )

        try:
            async with httpx.AsyncClient(timeout=self.settings.CD_RECRUIT_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code >= 400:
                    logger.error(
                        "[CD-RECRUIT] api error response",
                        status_code=response.status_code,
                        body=response.text,
                    )
                    raise CDRecruitException(
                        f"CD-Recruit endpoint returned status {response.status_code}: {response.text}"
                    )
                data = response.json()
        except httpx.HTTPError as exc:
            logger.exception("[CD-RECRUIT] connection error", error=str(exc))
            raise CDRecruitException("Failed to connect to CD-Recruit service.") from exc
        except CDRecruitException:
            raise
        except Exception as exc:
            logger.exception("[CD-RECRUIT] unexpected error", error=str(exc))
            raise CDRecruitException("Unexpected error during CD-Recruit handoff.") from exc

        # Extract returned candidate assessment objects/links
        returned_list = []
        if isinstance(data, dict):
            returned_list = data.get("invites") or data.get("candidates") or data.get("data") or [data]
        elif isinstance(data, list):
            returned_list = data

        return returned_list

