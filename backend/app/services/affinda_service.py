import time
from asyncio import to_thread
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_PERMANENT_FAILURE_STATUS_CODES = {401, 402, 403, 404}


class AffindaError(Exception):
    """Safe provider failure. Callers must fall back to the local pipeline."""


class AffindaCircuitBreaker:
    """Skip repeated Affinda calls once a permanent, account-level failure is seen.

    Errors like invalid auth or an exhausted parsing-credit balance are not
    per-document -- they fail identically for every document in a batch. Without
    this, each document still pays the full file-upload round trip to Affinda
    before falling back locally. A cooldown lets the breaker self-heal (e.g. once
    credits are topped up) without requiring a process restart.
    """

    _instance: "AffindaCircuitBreaker | None" = None

    def __init__(self, cooldown_seconds: float = 60.0) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._open = False
        self._opened_at = 0.0
        self._reason: str | None = None

    @classmethod
    def get_breaker(cls, cooldown_seconds: float = 60.0) -> "AffindaCircuitBreaker":
        if cls._instance is None:
            cls._instance = cls(cooldown_seconds)
        else:
            cls._instance.cooldown_seconds = cooldown_seconds
        return cls._instance

    @classmethod
    def reset_breaker(cls) -> None:
        cls._instance = None

    def can_call(self) -> bool:
        if not self._open:
            return True
        return (time.monotonic() - self._opened_at) >= self.cooldown_seconds

    def record_permanent_failure(self, reason: str) -> None:
        self._open = True
        self._opened_at = time.monotonic()
        self._reason = reason

    def record_success(self) -> None:
        self._open = False
        self._reason = None


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
        breaker = AffindaCircuitBreaker.get_breaker(
            getattr(self.settings, "AFFINDA_CIRCUIT_BREAKER_COOLDOWN_SECONDS", 60.0)
        )
        if not breaker.can_call():
            logger.warning(
                "[AFFINDA] circuit open, skipping request",
                document_type="resume" if document_type == self.settings.AFFINDA_RESUME_DOCUMENT_TYPE_ID else "job_description",
                filename=filename,
                reason=breaker._reason,
            )
            raise AffindaError(f"Affinda circuit open: {breaker._reason or 'previous permanent failure'}")
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
            if response.status_code in _PERMANENT_FAILURE_STATUS_CODES:
                breaker.record_permanent_failure(f"http_{response.status_code}")
            logger.warning(
                "[AFFINDA] response failed",
                document_type=provider_kind,
                http_status=response.status_code,
                error_type="AffindaHTTPError",
                sanitized_message="Provider returned a non-success status.",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            raise AffindaError(f"Affinda returned HTTP {response.status_code}.")

        # If document processing is asynchronous, poll GET /documents/{id} until ready
        identifier = payload.get("identifier") or (payload.get("meta") or {}).get("identifier")
        meta = payload.get("meta") or {}
        if identifier and (not meta.get("ready") or not isinstance(payload.get("data"), dict)):
            import asyncio
            max_polls = 20
            poll_count = 0
            poll_timeout = getattr(self.settings, "AFFINDA_POLL_TIMEOUT_SECONDS", 15.0)
            async with httpx.AsyncClient(timeout=poll_timeout) as poll_client:
                while poll_count < max_polls:
                    await asyncio.sleep(1.0)
                    poll_count += 1
                    try:
                        get_resp = await poll_client.get(
                            f"{endpoint}/{identifier}",
                            headers={"Authorization": f"Bearer {self.settings.AFFINDA_API_KEY}"},
                        )
                        if get_resp.status_code in {200, 201}:
                            polled_payload = get_resp.json()
                            if isinstance(polled_payload, dict):
                                payload = polled_payload
                                meta = payload.get("meta") or {}
                                if meta.get("ready") and isinstance(payload.get("data"), dict):
                                    break
                                if meta.get("failed"):
                                    break
                    except Exception:
                        pass

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
        breaker.record_success()
        logger.info(
            "[AFFINDA] attempt succeeded",
            document_type=provider_kind,
            http_status=response.status_code,
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
            provider_selected="affinda",
        )
        return payload
