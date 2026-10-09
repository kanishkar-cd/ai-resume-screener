"""Zoho Recruit API v2 client for fetching candidate resumes and job openings (JDs).

Auth: Supports a single combined OAuth refresh token or 3 separate scope-specific
refresh tokens (Job Openings, Candidates, Attachments). Exchanged for short-lived
access tokens, which are cached per scope and refreshed on expiry or 401.

Endpoints used (https://www.zoho.com/recruit/developer-guide/apiv2/):
  POST {accounts}/oauth/v2/token                          refresh -> access token
  GET  {api}/JobOpenings                                  paged list of job openings / JDs
  GET  {api}/JobOpenings/{id}                             job opening details
  GET  {api}/JobOpenings/{id}/Candidates                  candidates associated with a job opening
  GET  {api}/Candidates                                   global candidate list, If-Modified-Since
  GET  {api}/Candidates/{id}/Attachments                  attachment metadata
  GET  {api}/Candidates/{id}/Attachments/{attachment_id}  file download
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException

logger = structlog.get_logger(__name__)

# The local parsers handle PDF and DOCX only (see ALLOWED_RESUME_MIME_TYPES).
RESUME_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

CANDIDATE_FIELDS = (
    "Candidate_ID",
    "First_Name",
    "Last_Name",
    "Full_Name",
    "Email",
    "Mobile",
    "Phone",
    "Current_Job_Title",
    "Source",
    "Modified_Time",
)

JOB_OPENING_FIELDS = (
    "id",
    "Job_Opening_ID",
    "Posting_Title",
    "Job_Opening_Name",
    "Job_Description",
    "Required_Skills",
    "Job_Opening_Status",
    "Target_Date",
    "City",
    "Department",
    "Modified_Time",
)

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


@dataclass(frozen=True)
class ZohoJobOpening:
    id: str
    posting_title: str
    job_opening_id: str | None = None
    job_description: str | None = None
    required_skills: str | None = None
    job_status: str | None = None
    target_date: str | None = None
    city: str | None = None
    department: str | None = None
    modified_time: str | None = None
    no_of_candidates_associated: int = 0
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ZohoJobWithResumes:
    job_opening: ZohoJobOpening
    resumes: list[ZohoCandidateResume] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)  # candidate_id + reason
    candidates_seen: int = 0


_SHARED_ACCESS_TOKENS: dict[str, str] = {}
_SHARED_TOKEN_EXPIRES_AT: dict[str, float] = {}
_SHARED_TOKEN_LOCK = asyncio.Lock()
TOKEN_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / ".zoho_token_cache.json"


def _load_token_cache() -> None:
    try:
        if TOKEN_CACHE_FILE.exists():
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                now = time.time()
                for rt, entry in data.items():
                    exp = float(entry.get("expires_at", 0))
                    if exp > now:
                        _SHARED_ACCESS_TOKENS[rt] = entry["token"]
                        _SHARED_TOKEN_EXPIRES_AT[rt] = time.monotonic() + (exp - now)
    except Exception:
        pass


def _save_token_cache() -> None:
    try:
        data = {}
        now_mono = time.monotonic()
        now_epoch = time.time()
        for rt, token in _SHARED_ACCESS_TOKENS.items():
            remain = _SHARED_TOKEN_EXPIRES_AT.get(rt, 0.0) - now_mono
            if remain > 0:
                data[rt] = {
                    "token": token,
                    "expires_at": now_epoch + remain,
                }
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


_load_token_cache()


class ZohoRecruitClient:
    """Read-only Zoho Recruit client for job descriptions, candidates, and resume files."""

    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings or get_settings()
        self._transport = transport  # injected in tests
        self._access_tokens: dict[str, str] = {}
        self._token_expires_at: dict[str, float] = {}
        self._token_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        has_creds = bool(self.settings.ZOHO_CLIENT_ID and self.settings.ZOHO_CLIENT_SECRET)
        has_any_token = bool(
            self.settings.ZOHO_REFRESH_TOKEN
            or self.settings.ZOHO_JOB_OPENINGS_REFRESH_TOKEN
            or self.settings.ZOHO_CANDIDATES_REFRESH_TOKEN
            or self.settings.ZOHO_ATTACHMENTS_REFRESH_TOKEN
        )
        return has_creds and has_any_token

    @property
    def api_url(self) -> str:
        return self.settings.ZOHO_RECRUIT_API_URL.rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.settings.ZOHO_TIMEOUT_SECONDS, transport=self._transport)

    def _get_refresh_token_for_scope(self, scope_type: str) -> str | None:
        if scope_type == "job_openings":
            return self.settings.ZOHO_JOB_OPENINGS_REFRESH_TOKEN or self.settings.ZOHO_REFRESH_TOKEN
        if scope_type == "candidates":
            return self.settings.ZOHO_CANDIDATES_REFRESH_TOKEN or self.settings.ZOHO_REFRESH_TOKEN
        if scope_type == "attachments":
            return self.settings.ZOHO_ATTACHMENTS_REFRESH_TOKEN or self.settings.ZOHO_REFRESH_TOKEN
        return (
            self.settings.ZOHO_REFRESH_TOKEN
            or self.settings.ZOHO_JOB_OPENINGS_REFRESH_TOKEN
            or self.settings.ZOHO_CANDIDATES_REFRESH_TOKEN
            or self.settings.ZOHO_ATTACHMENTS_REFRESH_TOKEN
        )

    # ------------------------------------------------------------------ auth
    async def _get_access_token(self, scope_type: str = "default", *, force_refresh: bool = False) -> str:
        if not (self.settings.ZOHO_CLIENT_ID and self.settings.ZOHO_CLIENT_SECRET):
            raise ZohoRecruitNotConfiguredException(
                "Set ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET in .env."
            )
        refresh_token = self._get_refresh_token_for_scope(scope_type)
        if not refresh_token:
            raise ZohoRecruitNotConfiguredException(
                f"No refresh token configured for Zoho {scope_type}. Set ZOHO_REFRESH_TOKEN or scope-specific token in .env."
            )

        async with self._token_lock:
            cached_token = None
            if self._transport is None:
                cached_token = _SHARED_ACCESS_TOKENS.get(refresh_token)
                expires_at = _SHARED_TOKEN_EXPIRES_AT.get(refresh_token, 0.0)
            else:
                cached_token = self._access_tokens.get(refresh_token)
                expires_at = self._token_expires_at.get(refresh_token, 0.0)

            if not force_refresh and cached_token and time.monotonic() < expires_at:
                return cached_token

            url = f"{self.settings.ZOHO_ACCOUNTS_URL.rstrip('/')}/oauth/v2/token"
            params = {
                "refresh_token": refresh_token,
                "client_id": self.settings.ZOHO_CLIENT_ID,
                "client_secret": self.settings.ZOHO_CLIENT_SECRET,
                "grant_type": "refresh_token",
            }
            try:
                async with self._client() as client:
                    response = await client.post(url, params=params)
            except httpx.HTTPError as exc:
                raise ZohoRecruitException(f"Zoho token request failed for {scope_type}: {type(exc).__name__}") from exc

            body = _json(response)
            # Zoho reports bad credentials as HTTP 200 with {"error": "invalid_code"}.
            if response.status_code != 200 or "access_token" not in body:
                error = body.get("error_description") or body.get("error") or f"HTTP {response.status_code}"
                logger.error("[ZOHO] access token refresh failed", scope_type=scope_type, error=error)
                raise ZohoRecruitException(f"Zoho token refresh failed for {scope_type}: {error}")

            token = str(body["access_token"])
            expires_in = float(body.get("expires_in", 3600))
            if self._transport is None:
                _SHARED_ACCESS_TOKENS[refresh_token] = token
                _SHARED_TOKEN_EXPIRES_AT[refresh_token] = time.monotonic() + max(expires_in - TOKEN_REFRESH_MARGIN_SECONDS, 0)
                _save_token_cache()
            else:
                self._access_tokens[refresh_token] = token
                self._token_expires_at[refresh_token] = time.monotonic() + max(expires_in - TOKEN_REFRESH_MARGIN_SECONDS, 0)
            logger.info("[ZOHO] access token refreshed", scope_type=scope_type, expires_in=expires_in)
            return token

    # ------------------------------------------------------------------ transport
    @staticmethod
    def _infer_scope_type(path: str) -> str:
        clean_path = path.lstrip("/")
        if "associate" in clean_path:
            return "candidates"
        if "Attachments" in clean_path:
            return "attachments"
        if clean_path.startswith("Candidates"):
            return "candidates"
        if clean_path.startswith("JobOpenings") or clean_path.startswith("Job_Openings"):
            return "job_openings"
        return "default"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        scope_type: str | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        resolved_scope = scope_type or self._infer_scope_type(path)
        url = f"{self.api_url}/{path.lstrip('/')}"
        max_retries = self.settings.ZOHO_MAX_RETRIES
        refreshed_after_401 = False
        attempt = 0
        while True:
            token = await self._get_access_token(resolved_scope)
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

            if response.status_code == 401:
                body = _json(response)
                code = body.get("code") or ""
                if code == "OAUTH_SCOPE_MISMATCH" and not refreshed_after_401:
                    refreshed_after_401 = True
                    alt_scope = "candidates" if resolved_scope == "attachments" else ("attachments" if resolved_scope == "candidates" else None)
                    if alt_scope:
                        resolved_scope = alt_scope
                        continue
                if not refreshed_after_401:
                    refreshed_after_401 = True  # token revoked or expired early: refresh once
                    await self._get_access_token(resolved_scope, force_refresh=True)
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

    # ------------------------------------------------------------------ job openings (JDs)
    async def iter_job_openings(
        self,
        modified_since: datetime | None = None,
        *,
        status: str | None = None,
        per_page: int = MAX_PER_PAGE,
    ) -> AsyncIterator[ZohoJobOpening]:
        """Yield job openings (JDs), oldest-modified first, optionally filtered by update time or status."""
        headers = {"If-Modified-Since": _zoho_datetime(modified_since)} if modified_since else None
        page = 1
        while True:
            params: dict[str, Any] = {
                "page": page,
                "per_page": min(per_page, MAX_PER_PAGE),
                "fields": ",".join(JOB_OPENING_FIELDS),
                "sort_by": "Modified_Time",
                "sort_order": "asc",
            }
            response = await self._request("GET", "JobOpenings", params=params, headers=headers)
            if response.status_code in (204, 304):
                return
            body = _json(response)
            records = body.get("data") or []
            for record in records:
                job = _job_opening(record)
                if status and job.job_status and job.job_status.casefold() != status.casefold():
                    continue
                yield job
            if not (body.get("info") or {}).get("more_records"):
                return
            page += 1

    async def get_job_opening(self, job_id: str) -> ZohoJobOpening:
        """Fetch details of a single Job Opening by its Zoho ID."""
        try:
            response = await self._request("GET", f"JobOpenings/{job_id}", scope_type="job_openings")
        except ZohoRecruitException:
            response = await self._request("GET", f"Job_Openings/{job_id}", scope_type="job_openings")
        body = _json(response)
        data = body.get("data") or []
        if not data:
            raise ZohoRecruitException(f"Job Opening {job_id} not found in Zoho Recruit.")
        return _job_opening(data[0])

    async def iter_candidates_for_job(
        self, job_id: str, *, per_page: int = MAX_PER_PAGE
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield candidate records associated with a specific Job Opening."""
        # In Zoho Recruit v2, Job_Openings/{job_id}/associate queries associated candidates
        endpoints = [
            f"Job_Openings/{job_id}/associate",
            f"JobOpenings/{job_id}/associate",
        ]

        for endpoint in endpoints:
            page = 1
            has_records = False
            try:
                while True:
                    params: dict[str, Any] = {
                        "page": page,
                        "per_page": min(per_page, MAX_PER_PAGE),
                    }
                    response = await self._request("GET", endpoint, params=params, scope_type="candidates")
                    if response.status_code in (204, 304):
                        logger.info(
                            "[ZOHO] Job opening has 0 associated candidates in Zoho",
                            job_id=job_id,
                            endpoint=endpoint,
                        )
                        return
                    body = _json(response)
                    records = body.get("data") or []
                    for record in records:
                        has_records = True
                        yield record
                    if not (body.get("info") or {}).get("more_records"):
                        return
                    page += 1
                if has_records:
                    return
            except ZohoRecruitException as exc:
                logger.warning(
                    "[ZOHO] Associate endpoint call failed, attempting fallback",
                    endpoint=endpoint,
                    error=exc.message,
                )
                continue

        # Fallback: search Candidates module by criteria if /associate was not configured on tenant
        try:
            search_params = {
                "criteria": f"(Job_Opening_ID:equals:{job_id})",
                "fields": ",".join(CANDIDATE_FIELDS),
                "page": 1,
                "per_page": min(per_page, MAX_PER_PAGE),
            }
            response = await self._request("GET", "Candidates/search", params=search_params)
            if response.status_code not in (204, 304):
                body = _json(response)
                for record in body.get("data") or []:
                    yield record
        except Exception as exc:
            logger.warning("[ZOHO] Candidate search fallback failed", error=str(exc))

    # ------------------------------------------------------------------ candidates & attachments
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

    async def _download_single_resume(
        self, record: dict[str, Any]
    ) -> tuple[ZohoCandidateResume | None, dict[str, str] | None]:
        cand_obj = record.get("Candidate") or record.get("candidate")
        candidate_id = str(
            (cand_obj.get("id") if isinstance(cand_obj, dict) else None)
            or record.get("candidate_id")
            or record.get("id")
            or record.get("Candidate_ID")
            or ""
        )
        if not candidate_id:
            return None, {"candidate_id": "unknown", "reason": "No candidate ID found in record"}

        try:
            attachment = self.select_resume(await self.list_attachments(candidate_id))
            if attachment is None:
                return None, {"candidate_id": candidate_id, "reason": "no PDF/DOCX resume attached"}
            content, content_type, header_name = await self.download_attachment(candidate_id, attachment.id)
        except ZohoRecruitException as exc:
            return None, {"candidate_id": candidate_id, "reason": exc.message}

        if not content:
            return None, {"candidate_id": candidate_id, "reason": "empty resume file"}

        file_name = attachment.file_name or header_name or f"{candidate_id}{attachment.extension}"
        raw_full_name = (
            record.get("Full_Name")
            or record.get("Candidate_Name")
            or (cand_obj.get("name") if isinstance(cand_obj, dict) else None)
        )
        full_name = _text(raw_full_name) or " ".join(
            filter(None, [_text(record.get("First_Name")), _text(record.get("Last_Name"))])
        ) or None

        resume = ZohoCandidateResume(
            candidate_id=candidate_id,
            candidate_number=_text(record.get("Candidate_ID")),
            full_name=full_name,
            email=_text(record.get("Email")),
            phone=_text(record.get("Mobile")) or _text(record.get("Phone")),
            modified_time=_text(record.get("Modified_Time")),
            source=_text(record.get("Source")),
            attachment=attachment,
            file_name=file_name,
            content_type=RESUME_EXTENSIONS.get(attachment.extension) or content_type or "application/octet-stream",
            content=content,
        )
        return resume, None

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

        async def worker(record: dict[str, Any]) -> None:
            async with semaphore:
                resume, skip_reason = await self._download_single_resume(record)
                if skip_reason:
                    result.skipped.append(skip_reason)
                elif resume:
                    result.resumes.append(resume)

        await asyncio.gather(*(worker(record) for record in candidates))
        result.resumes.sort(key=lambda item: item.modified_time or "")
        logger.info(
            "[ZOHO] candidate resumes fetched",
            candidates_seen=result.candidates_seen,
            resumes=len(result.resumes),
            skipped=len(result.skipped),
            modified_since=_zoho_datetime(modified_since) if modified_since else None,
        )
        return result

    async def fetch_job_with_applicant_resumes(
        self, job_id: str, *, limit: int | None = None
    ) -> ZohoJobWithResumes:
        """Fetch a Job Description and all attached candidate resumes who applied for this opening."""
        job_opening = await self.get_job_opening(job_id)
        result = ZohoJobWithResumes(job_opening=job_opening)

        candidates: list[dict[str, Any]] = []
        async for record in self.iter_candidates_for_job(job_id):
            candidates.append(record)
            if limit is not None and len(candidates) >= limit:
                break
        result.candidates_seen = len(candidates)

        semaphore = asyncio.Semaphore(self.settings.ZOHO_DOWNLOAD_CONCURRENCY)

        async def worker(record: dict[str, Any]) -> None:
            async with semaphore:
                resume, skip_reason = await self._download_single_resume(record)
                if skip_reason:
                    result.skipped.append(skip_reason)
                elif resume:
                    result.resumes.append(resume)

        await asyncio.gather(*(worker(record) for record in candidates))
        result.resumes.sort(key=lambda item: item.modified_time or "")
        logger.info(
            "[ZOHO] job opening & applicant resumes fetched",
            job_id=job_id,
            posting_title=job_opening.posting_title,
            candidates_seen=result.candidates_seen,
            resumes=len(result.resumes),
            skipped=len(result.skipped),
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


def _job_opening(item: dict[str, Any]) -> ZohoJobOpening:
    raw_assoc = item.get("No_of_Candidates_Associated") or item.get("no_of_candidates_associated") or 0
    try:
        assoc_count = int(raw_assoc)
    except (TypeError, ValueError):
        assoc_count = 0

    return ZohoJobOpening(
        id=str(item.get("id") or ""),
        posting_title=_text(item.get("Posting_Title")) or _text(item.get("Job_Opening_Name")) or "Untitled Job Opening",
        job_opening_id=_text(item.get("Job_Opening_ID")),
        job_description=_text(item.get("Job_Description")),
        required_skills=_text(item.get("Required_Skills")),
        job_status=_text(item.get("Job_Opening_Status")),
        target_date=_text(item.get("Target_Date")),
        city=_text(item.get("City")),
        department=_text(item.get("Department")),
        modified_time=_text(item.get("Modified_Time")),
        no_of_candidates_associated=assoc_count,
        raw_data=item,
    )


def _zoho_datetime(value: datetime) -> str:
    """ISO 8601 with offset, as the If-Modified-Since header expects (naive values are taken as UTC)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")
