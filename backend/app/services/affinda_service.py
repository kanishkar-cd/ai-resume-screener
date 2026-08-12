from asyncio import to_thread
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class AffindaError(Exception):
    """Safe provider failure. Callers must fall back to the local pipeline."""


class AffindaService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.AFFINDA_API_KEY
            and self.settings.AFFINDA_WORKSPACE_ID
            and self.settings.AFFINDA_RESUME_DOCUMENT_TYPE_ID
            and self.settings.AFFINDA_JD_DOCUMENT_TYPE_ID
        )

    async def parse_resume(self, path: Path, filename: str, mime_type: str) -> dict[str, Any]:
        return await self._parse(path, filename, mime_type, self.settings.AFFINDA_RESUME_DOCUMENT_TYPE_ID)

    async def parse_job_description(self, path: Path, filename: str, mime_type: str) -> dict[str, Any]:
        return await self._parse(path, filename, mime_type, self.settings.AFFINDA_JD_DOCUMENT_TYPE_ID)

    async def _parse(self, path: Path, filename: str, mime_type: str, document_type: str | None) -> dict[str, Any]:
        if not self.configured or not document_type:
            logger.warning(
                "[AFFINDA] request skipped",
                configured=self.configured,
                document_type_configured=bool(document_type),
            )
            raise AffindaError("Affinda is not configured.")
        started_at = perf_counter()
        provider_kind = "resume" if document_type == self.settings.AFFINDA_RESUME_DOCUMENT_TYPE_ID else "job_description"
        logger.info(
            "[AFFINDA] attempt started",
            configured=True,
            document_type=provider_kind,
            filename=filename,
        )
        data = await to_thread(path.read_bytes)
        base = self.settings.AFFINDA_API_BASE_URL.rstrip("/")
        endpoint = (
            base
            if base.endswith("/v3/documents")
            else f"{base}/documents"
            if base.endswith("/v3")
            else f"{base}/v3/documents"
        )
        try:
            async with httpx.AsyncClient(timeout=self.settings.AFFINDA_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.settings.AFFINDA_API_KEY}"},
                    files={"file": (filename, data, mime_type or "application/octet-stream")},
                    data={
                        "workspace": self.settings.AFFINDA_WORKSPACE_ID,
                        "documentType": document_type,
                        "wait": "true",
                        "compact": "true",
                        "enableValidationTool": "false",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "[AFFINDA] request failed",
                document_type=provider_kind,
                http_status=None,
                error_type=type(exc).__name__,
                sanitized_message="Provider request could not be completed.",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            raise AffindaError(f"Affinda request failed: {type(exc).__name__}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning(
                "[AFFINDA] response failed",
                document_type=provider_kind,
                http_status=response.status_code,
                error_type=type(exc).__name__,
                sanitized_message="Provider returned a malformed response.",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            raise AffindaError("Affinda returned a malformed response.") from exc
        if response.status_code not in {200, 201}:
            logger.warning(
                "[AFFINDA] response failed",
                document_type=provider_kind,
                http_status=response.status_code,
                error_type="AffindaHTTPError",
                sanitized_message="Provider returned a non-success status.",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            raise AffindaError(f"Affinda returned HTTP {response.status_code}.")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise AffindaError("Affinda response did not contain structured data.")
        meta = payload.get("meta") or {}
        error = payload.get("error") or {}
        if meta.get("failed") or error.get("errorCode"):
            logger.warning(
                "[AFFINDA] processing failed",
                document_type=provider_kind,
                http_status=response.status_code,
                error_type="AffindaProcessingError",
                sanitized_message="Provider reported document processing failure.",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            raise AffindaError("Affinda document processing failed.")
        logger.info(
            "[AFFINDA] attempt succeeded",
            document_type=provider_kind,
            http_status=response.status_code,
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
            provider_selected="affinda",
        )
        return payload
