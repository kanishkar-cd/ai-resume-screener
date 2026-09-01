import asyncio
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
    """Service client for CD-Recruit Partner API integration."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_candidates(
        self,
        department_code: str | None = None,
        level: str | None = None,
        requisition_ref: str | None = None,
        candidates: list[dict[str, Any]] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        """Send candidate batch push to local CD-Recruit API (POST /partner/candidates).

        Expects HTTP 201 Created.
        Reuses the exact same idempotency_key for retries.
        """
        base_url = self.settings.CD_RECRUIT_BASE_URL.rstrip("/")
        url = f"{base_url}/api/v1/partner/candidates"
        api_key = self.settings.CD_RECRUIT_API_KEY or ""

        dept_code = department_code or kwargs.get("department_code") or "SOFTWARE_ENGINEERING"
        cand_list = candidates if candidates is not None else kwargs.get("candidates") or []
        req_ref = requisition_ref or kwargs.get("requisition_ref") or (args[0] if args else "")
        target_level = level or kwargs.get("level") or kwargs.get("category") or "EXPERIENCED"
        d_name = kwargs.get("drive_name") or "Hiring Drive"
        batch_idempotency_key = kwargs.get("idempotency_key") or str(uuid4())

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "Idempotency-Key": batch_idempotency_key,
        }

        payload = {
            "requisition_ref": req_ref,
            "department_code": dept_code,
            "level": target_level,
            "category": target_level,
            "drive_name": d_name,
            "candidates": cand_list,
        }

        logger.info(
            "[CD-RECRUIT] sending candidate handoff batch",
            url=url,
            requisition_ref=req_ref,
            department_code=dept_code,
            level=target_level,
            drive_name=d_name,
            candidate_count=len(cand_list),
            idempotency_key=batch_idempotency_key,
        )

        max_retries = 3
        backoff_delay = 1.0

        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.settings.CD_RECRUIT_TIMEOUT_SECONDS) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    if response.status_code in (201, 200):
                        logger.info(
                            "[CD-RECRUIT] candidate handoff successful",
                            status_code=response.status_code,
                            requisition_ref=req_ref,
                        )
                        data = response.json()
                        if isinstance(data, dict):
                            return data
                        return {"invites": data}

                    elif response.status_code == 429:
                        retry_after_hdr = response.headers.get("Retry-After")
                        wait_seconds = float(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else backoff_delay
                        logger.warning(
                            "[CD-RECRUIT] rate limit 429 encountered, respecting Retry-After",
                            attempt=attempt,
                            retry_after_seconds=wait_seconds,
                        )
                        if attempt < max_retries:
                            await asyncio.sleep(wait_seconds)
                            backoff_delay *= 2.0
                            continue
                        raise CDRecruitException(f"CD-Recruit rate limit exceeded (HTTP 429) after {max_retries} retries.")

                    elif response.status_code in (500, 503):
                        logger.warning(
                            "[CD-RECRUIT] transient server error encountered",
                            status_code=response.status_code,
                            attempt=attempt,
                            idempotency_key=batch_idempotency_key,
                        )
                        if attempt < max_retries:
                            await asyncio.sleep(backoff_delay)
                            backoff_delay *= 2.0
                            continue
                        raise CDRecruitException(
                            f"CD-Recruit endpoint returned status {response.status_code} after {max_retries} retries."
                        )

                    else:
                        logger.error(
                            "[CD-RECRUIT] non-retryable API error response",
                            status_code=response.status_code,
                            body=response.text,
                        )
                        raise CDRecruitException(
                            f"CD-Recruit endpoint returned non-retryable status {response.status_code}: {response.text}"
                        )

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.warning(
                    "[CD-RECRUIT] network error connecting to CD-Recruit service",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < max_retries:
                    await asyncio.sleep(backoff_delay)
                    backoff_delay *= 2.0
                    continue
                raise CDRecruitException(f"Failed to connect to CD-Recruit service: {exc}") from exc
            except CDRecruitException:
                raise
            except Exception as exc:
                logger.exception("[CD-RECRUIT] unexpected error", error=str(exc))
                raise CDRecruitException("Unexpected error during CD-Recruit handoff.") from exc

        raise CDRecruitException("CD-Recruit handoff failed after all retry attempts.")

    async def get_requisition_status(self, requisition_ref: str) -> dict[str, Any]:
        """Fetch current evaluation status for a requisition (GET /partner/requisitions/{ref}/status)
        and enrich with real assessment results (module scores, composite score, score band, decisions)
        from CD-Recruit admin results API.
        """
        base_url = self.settings.CD_RECRUIT_BASE_URL.rstrip("/")
        url = f"{base_url}/api/v1/partner/requisitions/{requisition_ref}/status"
        api_key = self.settings.CD_RECRUIT_API_KEY or ""

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.CD_RECRUIT_TIMEOUT_SECONDS) as client:
                data: dict[str, Any] = {}
                try:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        res_body = response.json()
                        if isinstance(res_body, dict):
                            data = res_body
                    elif response.status_code == 404:
                        logger.info("[CD-RECRUIT] requisition status not in partner index", requisition_ref=requisition_ref)
                    else:
                        logger.warning("[CD-RECRUIT] partner status endpoint returned code", status_code=response.status_code, requisition_ref=requisition_ref)
                except Exception as ex:
                    logger.warning("[CD-RECRUIT] unable to query partner requisition endpoint", error=str(ex))

                raw_candidates = data.get("candidates") or []
                processed_candidates = []
                for cand in raw_candidates:
                    cand_copy = dict(cand)
                    comp = cand_copy.get("composite_score") if cand_copy.get("composite_score") is not None else cand_copy.get("compositeScore")
                    calc_score: float | None = None
                    if comp is not None:
                        try:
                            val = float(comp)
                            if 0 < val <= 1.0:
                                val *= 100
                            calc_score = round(val, 1)
                        except (ValueError, TypeError):
                            pass
                    cand_copy["composite_score"] = calc_score

                    # Clean session_status: strictly use current drive invite/session status
                    inv_stat = str(cand_copy.get("invite_status") or "").upper()
                    sess_stat = str(cand_copy.get("session_status") or "").upper()
                    if not sess_stat or sess_stat == "NONE" or (inv_stat == "PENDING" and sess_stat in ("NOT_STARTED", "")):
                        cand_copy["session_status"] = "NOT_STARTED"
                    else:
                        cand_copy["session_status"] = sess_stat

                    # Score status
                    if calc_score is not None:
                        cand_copy["score_status"] = "GRADED"
                    elif cand_copy.get("score_status"):
                        cand_copy["score_status"] = str(cand_copy["score_status"]).upper()
                    else:
                        cand_copy["score_status"] = "PENDING"

                    processed_candidates.append(cand_copy)

                data["candidates"] = processed_candidates
                if processed_candidates:
                    has_submitted = any(c.get("session_status", "").upper() == "SUBMITTED" for c in processed_candidates)
                    has_graded = any(c.get("composite_score") is not None or c.get("decision") in ("ADVANCE", "REJECT", "PASS", "FAIL", "APPROVED", "REJECTED") for c in processed_candidates)
                    data["session_status"] = "in_progress" if has_submitted else "not_started"
                    data["score_status"] = "graded" if has_graded else "pending"

                return data

        except httpx.HTTPError as exc:
            logger.error("[CD-RECRUIT] network error fetching requisition status", requisition_ref=requisition_ref, error=str(exc))
            raise CDRecruitException(f"Network error fetching requisition status: {exc}") from exc
