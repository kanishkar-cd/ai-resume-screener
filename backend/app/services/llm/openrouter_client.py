from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any
import httpx
import structlog

from app.core.config import Settings, get_settings
from app.schemas.matching import MatchVerdict
from app.services.llm.batch_pipeline import (
    ResumeBatchContext,
    parse_and_validate_multi_resume_response,
    build_failed_verdicts,
    build_system_evaluation_prompt,
)

logger = structlog.get_logger(__name__)


class OpenRouterBatchExecutor:
    """
    Executes post-deterministic multi-resume batch evaluation against OpenRouter.
    Acts strictly as a secondary fallback provider when Groq cannot complete evaluation.
    """
    _client: httpx.AsyncClient | None = None

    def __init__(
        self,
        settings: Settings | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.max_retries = max_retries if max_retries is not None else int(getattr(self.settings, "OPENROUTER_MAX_RETRIES", 1))

    @classmethod
    def _get_client(cls, timeout: float) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(timeout=timeout)
        return cls._client

    @property
    def enabled(self) -> bool:
        """True if OpenRouter is enabled and has a valid API key configured."""
        return bool(
            getattr(self.settings, "openrouter_is_configured", False)
            or (
                getattr(self.settings, "OPENROUTER_ENABLED", True)
                and bool(getattr(self.settings, "OPENROUTER_API_KEY", None))
            )
        )

    def build_payload(self, batch: list[ResumeBatchContext]) -> dict[str, Any]:
        """Constructs a structured multi-resume prompt payload for OpenRouter."""
        resumes_payload = []
        for ctx in batch:
            req_list = [
                {
                    "requirement_id": r.requirement_id,
                    "requirement_type": "skill" if getattr(r.kind, "value", str(r.kind)) in {"skill", "required_skills", "preferred_skills"} else "responsibility",
                    "kind": getattr(r.kind, "value", str(r.kind)),
                    "text": r.text,
                    "required": r.required,
                    "importance": getattr(r, "importance", "important"),
                    "allowed_evidence_ids": sorted(list(ctx.allowed_evidence.get(r.requirement_id, set()))),
                }
                for r in ctx.requirements
            ]
            relevant_ev_ids = {eid for ids in ctx.allowed_evidence.values() for eid in ids}
            ev_list = [
                {
                    "evidence_id": e.evidence_id,
                    "kind": e.kind,
                    "text": e.text[:400] if len(e.text) > 400 else e.text,
                    "canonical_terms": e.canonical_terms[:10] if e.canonical_terms else [],
                }
                for e in ctx.candidate_evidence
                if not relevant_ev_ids or e.evidence_id in relevant_ev_ids
            ]
            resumes_payload.append({
                "resume_id": ctx.resume_id,
                "requirements": req_list,
                "candidate_evidence": ev_list,
            })

        system_prompt = build_system_evaluation_prompt()
        model = getattr(self.settings, "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
        max_output_tokens = int(getattr(self.settings, "OPENROUTER_MAX_COMPLETION_TOKENS", 4096))
        return {
            "model": model,
            "temperature": 0,
            "max_tokens": max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({"resumes": resumes_payload})},
            ],
            "response_format": {"type": "json_object"},
        }

    async def _call_openrouter_api(
        self, payload: dict[str, Any], timeout_sec: float
    ) -> str:
        """Invokes OpenRouter chat completion API."""
        client = self._get_client(timeout_sec)
        base_url = str(getattr(self.settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
        api_key = str(getattr(self.settings, "OPENROUTER_API_KEY", "") or getattr(self.settings, "OPEN_ROUTER", "") or "")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": str(getattr(self.settings, "OPENROUTER_HTTP_REFERER", "https://clouddestinations.com")),
            "X-Title": str(getattr(self.settings, "OPENROUTER_APP_TITLE", "AI Resume Screener")),
            "Content-Type": "application/json",
        }

        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout_sec,
        )
        response.raise_for_status()
        resp_json = response.json()
        self._last_response_usage = resp_json.get("usage", {})
        choices = resp_json.get("choices", [])
        choice = choices[0] if choices else {}
        return choice.get("message", {}).get("content", "")

    async def execute_batch_with_retry(
        self,
        batch: list[ResumeBatchContext],
        max_retries: int | None = None,
    ) -> dict[str, list[MatchVerdict]]:
        """
        Executes a batch of unresolved resumes against OpenRouter with bounded retry.
        Preserves isolated partial retry if subset fails.
        """
        if not batch:
            return {}

        if not self.enabled:
            logger.warning(
                "openrouter_batch_executor_disabled_or_no_api_key",
                enabled=bool(getattr(self.settings, "OPENROUTER_ENABLED", True)),
                has_key=bool(getattr(self.settings, "OPENROUTER_API_KEY", None) or getattr(self.settings, "OPEN_ROUTER", None)),
            )
            return build_failed_verdicts(
                batch,
                failure_reason="OPENROUTER_DISABLED_OR_NO_API_KEY",
                settings=self.settings,
            )

        effective_max_retries = max_retries if max_retries is not None else self.max_retries
        total_attempts = max(1, effective_max_retries + 1)
        successful_results: dict[str, list[MatchVerdict]] = {}
        pending_batch = list(batch)
        attempts = 0
        timeout_sec = float(getattr(self.settings, "OPENROUTER_TIMEOUT_SECONDS", 30.0))

        while pending_batch and attempts < total_attempts:
            attempts += 1
            batch_resume_ids = [ctx.resume_id for ctx in pending_batch]
            t0 = time.monotonic()

            logger.info(
                "openrouter_batch_request_started",
                provider="openrouter",
                batch_size=len(pending_batch),
                resume_ids=batch_resume_ids,
                attempt=attempts,
                max_attempts=total_attempts,
            )

            try:
                payload = self.build_payload(pending_batch)
                content = await self._call_openrouter_api(payload, timeout_sec)
                duration_ms = (time.monotonic() - t0) * 1000.0

                parsed_results = parse_and_validate_multi_resume_response(
                    content, pending_batch, settings=self.settings
                )

                if parsed_results:
                    failed_in_attempt: list[ResumeBatchContext] = []
                    for ctx in pending_batch:
                        if ctx.resume_id in parsed_results and parsed_results[ctx.resume_id]:
                            successful_results[ctx.resume_id] = parsed_results[ctx.resume_id]
                        else:
                            failed_in_attempt.append(ctx)

                    logger.info(
                        "openrouter_batch_request_completed",
                        provider="openrouter",
                        batch_size=len(pending_batch),
                        success_count=len(pending_batch) - len(failed_in_attempt),
                        failed_count=len(failed_in_attempt),
                        duration_ms=round(duration_ms, 2),
                        attempt=attempts,
                    )

                    pending_batch = failed_in_attempt
                else:
                    logger.warning(
                        "openrouter_batch_empty_or_invalid_parse",
                        provider="openrouter",
                        attempt=attempts,
                        duration_ms=round(duration_ms, 2),
                    )
                    if attempts < total_attempts:
                        await asyncio.sleep(0.5)

            except Exception as exc:
                duration_ms = (time.monotonic() - t0) * 1000.0
                err_type = type(exc).__name__
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                
                logger.error(
                    "openrouter_batch_request_exception",
                    provider="openrouter",
                    attempt=attempts,
                    error_type=err_type,
                    status_code=status_code,
                    duration_ms=round(duration_ms, 2),
                )
                
                # Auth or not found errors are non-retryable
                if status_code in {401, 403, 404}:
                    break

                if attempts < total_attempts:
                    await asyncio.sleep(0.5)

        # For any resumes that failed all OpenRouter attempts, mark as EVALUATION_FAILED
        if pending_batch:
            failed_verdicts = build_failed_verdicts(
                pending_batch,
                failure_reason="AI Review Unavailable — OpenRouter fallback failure",
                settings=self.settings,
            )
            for r_id, v_list in failed_verdicts.items():
                if r_id not in successful_results:
                    successful_results[r_id] = v_list

        return successful_results
