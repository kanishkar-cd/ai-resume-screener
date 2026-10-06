"""Zoho Recruit API v2 client for fetching candidate resumes.

Auth: a long-lived OAuth refresh token (from a Zoho API-console client) is
exchanged for short-lived access tokens, which are cached and refreshed on
expiry or on a 401. Calls retry on 429/5xx/network errors with backoff.

Endpoints used (https://www.zoho.com/recruit/developer-guide/apiv2/):
  POST {accounts}/oauth/v2/token                         refresh -> access token
  GET  {api}/Candidates                                  paged list, If-Modified-Since
  GET  {api}/Candidates/{id}/Attachments                 attachment metadata
  GET  {api}/Candidates/{id}/Attachments/{attachment_id} file download
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Any

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException

logger = structlog.get_logger(__name__)

# The local parsers handle PDF and DOCX only (see ALLOWED_RESUME_MIME_TYPES).
RESUME_EXTENSIONS = {".pdf": "application/pdf",
                     ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
CANDIDATE_FIELDS = ("Candidate_ID", "First_Name", "Last_Name", "Full_Name", "Email", "Mobile", "Phone",
                    "Current_Job_Title", "Source", "Modified_Time")
TOKEN_REFRESH_MARGIN_SECONDS = 60
MAX_PER_PAGE = 200


class ZohoRecruitException(AppException):
    status_code = 502
    error_code = "ZOHO_RECRUIT_INTEGRATION_FAILED"
    default_message = "Zoho Recruit integration call failed."


class ZohoRecruitNotConfiguredException(ZohoRecruitException):
    status_code = 503
    error_code = "ZOHO_RECRUIT_NOT_CONFIGURED"
    default_message = "Zoho Recruit credentials are not configured."


@dataclass(frozen=True)
class ZohoAttachment:
    id: str
    file_name: str
    size: int | None
    modified_time: str | None
    category: str | None

    @property
    def extension(self) -> str:
        return PurePath(self.file_name).suffix.lower()


@dataclass(frozen=True)
class ZohoCandidateResume:
    candidate_id: str
    candidate_number: str | None
    full_name: str | None
    email: str | None
    phone: str | None
    modified_time: str | None
    source: str | None
    attachment: ZohoAttachment
    file_name: str
    content_type: str
    content: bytes


@dataclass
class ZohoResumeFetchResult:
    resumes: list[ZohoCandidateResume] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)  # candidate_id + reason
    candidates_seen: int = 0


class ZohoRecruitClient:
    """Read-only Zoho Recruit client for candidate records and their resume files."""

    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings or get_settings()
        self._transport = transport  # injected in tests
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.settings.ZOHO_CLIENT_ID and self.settings.ZOHO_CLIENT_SECRET and self.settings.ZOHO_REFRESH_TOKEN)

    @property
    def api_url(self) -> str:
        return self.settings.ZOHO_RECRUIT_API_URL.rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.settings.ZOHO_TIMEOUT_SECONDS, transport=self._transport)

    # ------------------------------------------------------------------ auth
    async def _get_access_token(self, *, force_refresh: bool = False) -> str:
        if not self.configured:
            raise ZohoRecruitNotConfiguredException(
                "Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN in .env."
            )
        async with self._token_lock:
            if not force_refresh and self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            url = f"{self.settings.ZOHO_ACCOUNTS_URL.rstrip('/')}/oauth/v2/token"
            params = {
                "refresh_token": self.settings.ZOHO_REFRESH_TOKEN,
                "client_id": self.settings.ZOHO_CLIENT_ID,
                "client_secret": self.settings.ZOHO_CLIENT_SECRET,
                "grant_type": "refresh_token",
            }
            try:
                async with self._client() as client:
                    response = await client.post(url, params=params)
            except httpx.HTTPError as exc:
                raise ZohoRecruitException(f"Zoho token request failed: {type(exc).__name__}") from exc
            body = _json(response)
            # Zoho reports bad credentials as HTTP 200 with {"error": "invalid_code"}.
            if response.status_code != 200 or "access_token" not in body:
                error = body.get("error") or f"HTTP {response.status_code}"
                logger.error("[ZOHO] access token refresh failed", error=error)
                raise ZohoRecruitException(f"Zoho token refresh failed: {error}")
            self._access_token = str(body["access_token"])
            expires_in = float(body.get("expires_in", 3600))
            self._token_expires_at = time.monotonic() + max(expires_in - TOKEN_REFRESH_MARGIN_SECONDS, 0)
            logger.info("[ZOHO] access token refreshed", expires_in=expires_in)
            return self._access_token

    # ------------------------------------------------------------------ transport
    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        url = f"{self.api_url}/{path.lstrip('/')}"
        max_retries = self.settings.ZOHO_MAX_RETRIES
        refreshed_after_401 = False
        attempt = 0
        while True:
            token = await self._get_access_token()
            request_headers = {"Authorization": f"Zoho-oauthtoken {token}", **(headers or {})}
            try:
                async with self._client() as client:
                    response = await client.request(method, url, params=params, headers=request_headers)
            except httpx.HTTPError as exc:
                if attempt < max_retries:
                    attempt += 1
                    await self._backoff(attempt, None, reason=type(exc).__name__, path=path)
                    continue
                raise ZohoRecruitException(f"Zoho request failed: {type(exc).__name__}") from exc

            if response.status_code == 401 and not refreshed_after_401:
                refreshed_after_401 = True  # token revoked or expired early: refresh once
                await self._get_access_token(force_refresh=True)
                continue
            if (response.status_code == 429 or response.status_code >= 500) and attempt < max_retries:
                attempt += 1
                await self._backoff(attempt, response.headers.get("Retry-After"), reason=str(response.status_code), path=path)
                continue
            if response.status_code >= 400:
                body = _json(response)
                code = body.get("code") or body.get("error") or f"HTTP {response.status_code}"
                logger.error("[ZOHO] request failed", path=path, status_code=response.status_code, code=code)
                raise ZohoRecruitException(f"Zoho Recruit {method} {path} failed: {code}")
            return response

    @staticmethod
    async def _backoff(attempt: int, retry_after: str | None, *, reason: str, path: str) -> None:
        delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2.0 ** (attempt - 1), 30.0)
        logger.warning("[ZOHO] retrying request", path=path, reason=reason, attempt=attempt, delay_seconds=delay)
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------ candidates
    async def iter_candidates(
        self, modified_since: datetime | None = None, *, per_page: int = MAX_PER_PAGE
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield candidate records, oldest-modified first, optionally only those changed since a time."""
        headers = {"If-Modified-Since": _zoho_datetime(modified_since)} if modified_since else None
        page = 1
        while True:
            params = {
                "page": page,
                "per_page": min(per_page, MAX_PER_PAGE),
                "fields": ",".join(CANDIDATE_FIELDS),
                "sort_by": "Modified_Time",
                "sort_order": "asc",
            }
            response = await self._request("GET", "Candidates", params=params, headers=headers)
            if response.status_code in (204, 304):  # nothing (new) to return
                return
            body = _json(response)
            for record in body.get("data") or []:
                yield record
            if not (body.get("info") or {}).get("more_records"):
                return
            page += 1

    async def list_attachments(self, candidate_id: str) -> list[ZohoAttachment]:
        attachments: list[ZohoAttachment] = []
        page = 1
        while True:
            response = await self._request(
                "GET", f"Candidates/{candidate_id}/Attachments", params={"page": page, "per_page": MAX_PER_PAGE}
            )
            if response.status_code == 204:
                break
            body = _json(response)
            attachments.extend(_attachment(item) for item in body.get("data") or [] if item.get("id"))
            if not (body.get("info") or {}).get("more_records"):
                break
            page += 1
        return attachments

    async def download_attachment(self, candidate_id: str, attachment_id: str) -> tuple[bytes, str | None, str | None]:
        """Return (content, content_type, file_name from Content-Disposition)."""
        response = await self._request("GET", f"Candidates/{candidate_id}/Attachments/{attachment_id}")
        disposition = response.headers.get("Content-Disposition", "")
        match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", disposition, re.I)
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip() or None
        return response.content, content_type, match.group(1) if match else None

    @staticmethod
    def select_resume(attachments: list[ZohoAttachment]) -> ZohoAttachment | None:
        """Pick the candidate's current resume: a PDF/DOCX, preferring the 'Resume' category, newest first."""
        files = [a for a in attachments if a.extension in RESUME_EXTENSIONS]
        if not files:
            return None

        def rank(item: ZohoAttachment) -> tuple[int, int, str]:
            is_resume_category = int((item.category or "").casefold() == "resume")
            named_like_resume = int(bool(re.search(r"resume|cv|curriculum", item.file_name, re.I)))
            return is_resume_category, named_like_resume, item.modified_time or ""

        return max(files, key=rank)

    async def fetch_candidate_resumes(
        self, modified_since: datetime | None = None, *, limit: int | None = None
    ) -> ZohoResumeFetchResult:
        """Fetch candidates (optionally changed since a time) together with their resume files."""
        result = ZohoResumeFetchResult()
        candidates: list[dict[str, Any]] = []
        async for record in self.iter_candidates(modified_since):
            candidates.append(record)
            if limit is not None and len(candidates) >= limit:
                break
        result.candidates_seen = len(candidates)

        semaphore = asyncio.Semaphore(self.settings.ZOHO_DOWNLOAD_CONCURRENCY)

        async def fetch_one(record: dict[str, Any]) -> None:
            candidate_id = str(record.get("id"))
            async with semaphore:
                try:
                    attachment = self.select_resume(await self.list_attachments(candidate_id))
                    if attachment is None:
                        result.skipped.append({"candidate_id": candidate_id, "reason": "no PDF/DOCX resume attached"})
                        return
                    content, content_type, header_name = await self.download_attachment(candidate_id, attachment.id)
                except ZohoRecruitException as exc:
                    result.skipped.append({"candidate_id": candidate_id, "reason": exc.message})
                    return
            if not content:
                result.skipped.append({"candidate_id": candidate_id, "reason": "empty resume file"})
                return
            file_name = attachment.file_name or header_name or f"{candidate_id}{attachment.extension}"
            result.resumes.append(ZohoCandidateResume(
                candidate_id=candidate_id,
                candidate_number=_text(record.get("Candidate_ID")),
                full_name=_text(record.get("Full_Name"))
                or " ".join(filter(None, [_text(record.get("First_Name")), _text(record.get("Last_Name"))])) or None,
                email=_text(record.get("Email")),
                phone=_text(record.get("Mobile")) or _text(record.get("Phone")),
                modified_time=_text(record.get("Modified_Time")),
                source=_text(record.get("Source")),
                attachment=attachment,
                file_name=file_name,
                content_type=RESUME_EXTENSIONS.get(attachment.extension) or content_type or "application/octet-stream",
                content=content,
            ))

        await asyncio.gather(*(fetch_one(record) for record in candidates))
        result.resumes.sort(key=lambda item: item.modified_time or "")
        logger.info(
            "[ZOHO] candidate resumes fetched",
            candidates_seen=result.candidates_seen,
            resumes=len(result.resumes),
            skipped=len(result.skipped),
            modified_since=_zoho_datetime(modified_since) if modified_since else None,
        )
        return result


def _json(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _text(value: Any) -> str | None:
    if isinstance(value, dict):  # lookup fields come back as {"name": ..., "id": ...}
        value = value.get("name") or value.get("display_value")
    text = str(value).strip() if value is not None else ""
    return text or None


def _attachment(item: dict[str, Any]) -> ZohoAttachment:
    # The category label is not fixed in the documented schema; accept the shapes Zoho uses.
    category = item.get("Category") or item.get("Attachment_Category") or item.get("$attachment_category")
    size = item.get("Size")
    return ZohoAttachment(
        id=str(item["id"]),
        file_name=str(item.get("File_Name") or item.get("file_name") or ""),
        size=int(size) if str(size or "").isdigit() else None,
        modified_time=_text(item.get("Modified_Time")),
        category=_text(category),
    )


def _zoho_datetime(value: datetime) -> str:
    """ISO 8601 with offset, as the If-Modified-Since header expects (naive values are taken as UTC)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")
