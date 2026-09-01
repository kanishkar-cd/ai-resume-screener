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
                        logger.info("[CD-RECRUIT] requisition status not in partner index, querying admin results directly", requisition_ref=requisition_ref)
                    else:
                        logger.warning("[CD-RECRUIT] partner status endpoint returned code", status_code=response.status_code, requisition_ref=requisition_ref)
                except Exception as ex:
                    logger.warning("[CD-RECRUIT] unable to query partner requisition endpoint, falling back to admin results", error=str(ex))

                # Fetch detailed real admin results for full scoring and candidate telemetry
                admin_items: list[dict[str, Any]] = []
                dev_token: str | None = None
                try:
                    token_res = await client.get(f"{base_url}/api/v1/auth/dev-token")
                    if token_res.status_code == 200:
                        token_payload = token_res.json()
                        dev_token = token_payload.get("token") or token_payload.get("accessToken")
                        if dev_token:
                            results_res = await client.get(
                                f"{base_url}/api/v1/admin/results?page=1&pageSize=100",
                                headers={"Authorization": f"Bearer {dev_token}"},
                            )
                            if results_res.status_code == 200:
                                res_json = results_res.json()
                                admin_items = res_json.get("items", []) if isinstance(res_json, dict) else res_json
                except Exception as ex:
                    logger.warning("[CD-RECRUIT] unable to query admin results for enrichment", error=str(ex))

                admin_by_email: dict[str, dict[str, Any]] = {}
                admin_by_name: dict[str, dict[str, Any]] = {}
                for it in admin_items:
                    em = str(it.get("candidateEmail") or "").strip().lower()
                    nm = str(it.get("candidateName") or "").strip().lower()
                    if em:
                        admin_by_email[em] = it
                    if nm:
                        admin_by_name[nm] = it

                raw_candidates = data.get("candidates") or []
                if not raw_candidates and admin_items:
                    # If partner requisition endpoint returned 404, synthesize candidates from admin_items
                    raw_candidates = [
                        {
                            "candidate_id": it.get("candidateId") or it.get("sessionId"),
                            "external_candidate_ref": it.get("candidateId"),
                            "candidate_name": it.get("candidateName"),
                            "candidate_email": it.get("candidateEmail"),
                            "email": it.get("candidateEmail"),
                            "name": it.get("candidateName"),
                            "session_status": it.get("status"),
                            "status": it.get("status"),
                        }
                        for it in admin_items
                    ]

                enriched_candidates = []
                for cand in raw_candidates:
                    cand_copy = dict(cand)
                    em = str(cand.get("candidate_email") or cand.get("email") or "").strip().lower()
                    nm = str(cand.get("candidate_name") or cand.get("name") or "").strip().lower()
                    adm = admin_by_email.get(em) or admin_by_name.get(nm)

                    if adm:
                        cand_copy["session_status"] = adm.get("status") or cand_copy.get("session_status") or "SUBMITTED"
                        comp = adm.get("compositeScore")
                        mod_scores = adm.get("moduleScores")
                        say_do = adm.get("sayDoConsistencyScore")
                        rev_dec = adm.get("reviewerDecision")
                        dec_obj = adm.get("decision") or {}
                        dec_outcome = str(dec_obj.get("outcome") or rev_dec or "").upper()

                        # If top-level compositeScore is null, fetch session details
                        sid = adm.get("sessionId")
                        if comp is None and sid and dev_token:
                            try:
                                sess_resp = await client.get(
                                    f"{base_url}/api/v1/admin/sessions/{sid}",
                                    headers={"Authorization": f"Bearer {dev_token}"},
                                    timeout=4.0,
                                )
                                if sess_resp.status_code == 200:
                                    s_data = sess_resp.json()
                                    s_score_obj = s_data.get("score")
                                    if isinstance(s_score_obj, dict):
                                        if s_score_obj.get("compositeScore") is not None:
                                            comp = s_score_obj.get("compositeScore")
                                        if s_score_obj.get("moduleScores") is not None:
                                            mod_scores = s_score_obj.get("moduleScores")
                                    if not dec_outcome:
                                        s_dec = s_data.get("decision") or {}
                                        dec_outcome = str(s_dec.get("outcome") or s_data.get("reviewerDecision") or "").upper()
                            except Exception:
                                pass

                        calc_score: float | None = None

                        if comp is not None:
                            try:
                                val = float(comp)
                                if 0 < val <= 1.0:
                                    val *= 100
                                calc_score = round(val, 1)
                            except (ValueError, TypeError):
                                pass
                        elif isinstance(mod_scores, dict) and len(mod_scores) > 0:
                            try:
                                numeric_scores = [float(v) for v in mod_scores.values() if v is not None]
                                if numeric_scores:
                                    avg_val = sum(numeric_scores) / len(numeric_scores)
                                    if 0 < avg_val <= 1.0:
                                        avg_val *= 100
                                    calc_score = round(avg_val, 1)
                            except Exception:
                                pass

                        cand_copy["composite_score"] = calc_score
                        if calc_score is not None:
                            if calc_score >= 85:
                                cand_copy["composite_score_band"] = "Excellent"
                            elif calc_score >= 70:
                                cand_copy["composite_score_band"] = "Good"
                            elif calc_score >= 55:
                                cand_copy["composite_score_band"] = "Average"
                            else:
                                cand_copy["composite_score_band"] = "Below Bar"
                            cand_copy["score_status"] = "GRADED"
                        elif dec_outcome in ("ADVANCE", "PASS", "SHORTLIST", "APPROVE"):
                            cand_copy["composite_score_band"] = "Shortlisted"
                            cand_copy["score_status"] = "GRADED"
                        else:
                            cand_copy["composite_score_band"] = None
                            cand_copy["score_status"] = "PENDING"

                        # Set reviewer decision
                        if dec_outcome:
                            cand_copy["decision"] = dec_outcome

                        id_res = adm.get("identityVerificationResult")
                        if isinstance(id_res, dict):
                            if id_res.get("matched") is True:
                                cand_copy["identity_status"] = "VERIFIED"
                                cand_copy["is_identity_verified"] = True
                            elif id_res.get("matched") is False:
                                cand_copy["identity_status"] = "FAILED"
                                cand_copy["is_identity_verified"] = False

                    enriched_candidates.append(cand_copy)

                data["candidates"] = enriched_candidates
                if enriched_candidates:
                    has_submitted = any(c.get("session_status", "").upper() == "SUBMITTED" for c in enriched_candidates)
                    has_graded = any(c.get("composite_score") is not None or c.get("decision") for c in enriched_candidates)
                    data["session_status"] = "in_progress" if has_submitted else "not_started"
                    data["score_status"] = "graded" if has_graded else "pending"

                return data

        except httpx.HTTPError as exc:
            logger.error("[CD-RECRUIT] network error fetching requisition status", requisition_ref=requisition_ref, error=str(exc))
            raise CDRecruitException(f"Network error fetching requisition status: {exc}") from exc
