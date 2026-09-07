from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any
import httpx
import structlog

from app.core.config import Settings, get_settings
from app.schemas.matching import (
    Evidence,
    LLMVerdictBatch,
    MatchStatus,
    MatchVerdict,
    Requirement,
)
from app.services.llm.provider_types import (
    LLMRequest,
    ProviderResult,
    ProviderStatus,
)

logger = structlog.get_logger(__name__)


def _get_setting(settings: Any, key: str, default: Any) -> Any:
    return getattr(settings, key, default) if hasattr(settings, key) else default


class BaseLLMAdapter:
    """Abstract base for LLM provider adapters."""
    provider_name: str = "base"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        raise NotImplementedError

    def can_call(self, circuit_breaker: Any) -> bool:
        if not self.enabled:
            return False
        return circuit_breaker.can_call(self.provider_name)

    async def execute(self, request: LLMRequest, allow_retries: bool = False) -> ProviderResult:
        raise NotImplementedError


class GroqAdapter(BaseLLMAdapter):
    provider_name: str = "groq"
    _client: httpx.AsyncClient | None = None

    @classmethod
    def _get_client(cls, timeout: float) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(timeout=timeout)
        return cls._client

    @property
    def enabled(self) -> bool:
        return bool(
            _get_setting(self.settings, "ENABLE_HYBRID_MATCHING", True)
            and _get_setting(self.settings, "GROQ_API_KEY", None)
        )

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        from app.services.matching_service import GroqMatchEvaluator
        evaluator = GroqMatchEvaluator(self.settings)
        payload = evaluator._payload(request.requirements, request.evidence, request.allowed_evidence)
        return payload

    async def execute(self, request: LLMRequest, allow_retries: bool = False) -> ProviderResult:
        t0 = time.monotonic()
        if not self.enabled:
            return ProviderResult(
                provider=self.provider_name,
                status=ProviderStatus.DISABLED,
                error_message="Groq provider is disabled or GROQ_API_KEY is not configured.",
                latency_ms=0.0,
            )

        from app.services.matching_service import (
            GroqTokenBudgetGate,
            ProviderCircuitBreaker,
            _parse_llm_batch_response,
        )

        breaker = ProviderCircuitBreaker.get_breaker(self.settings)
        if not breaker.can_call("groq"):
            return ProviderResult(
                provider=self.provider_name,
                status=ProviderStatus.CIRCUIT_OPEN,
                error_message="Groq circuit breaker is open.",
                latency_ms=0.0,
            )

        payload = self.build_payload(request)
        gate = GroqTokenBudgetGate.get_gate(self.settings)
        estimated_tokens = gate.estimate_tokens(payload)

        has_budget = await gate.try_reserve(estimated_tokens)
        if not has_budget:
            return ProviderResult(
                provider=self.provider_name,
                status=ProviderStatus.BUDGET_EXHAUSTED,
                error_message="Groq token budget is exhausted.",
                latency_ms=(time.monotonic() - t0) * 1000.0,
                is_retryable=True,
            )

        timeout = float(_get_setting(self.settings, "GROQ_TIMEOUT_SECONDS", 30.0))
        client = self._get_client(timeout)
        base_url = str(_get_setting(self.settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")).rstrip("/")
        api_key = str(_get_setting(self.settings, "GROQ_API_KEY", ""))

        try:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()

            resp_json = response.json()
            usage = resp_json.get("usage", {})
            prompt_toks = usage.get("prompt_tokens", 0)
            comp_toks = usage.get("completion_tokens", 0)
            tot_toks = usage.get("total_tokens") or (prompt_toks + comp_toks)
            usage_stats = {"prompt_tokens": prompt_toks, "completion_tokens": comp_toks, "total_tokens": tot_toks}

            await gate.record_response(estimated_tokens, response=response, actual_tokens=tot_toks)
            breaker.record_success("groq")

            choices = resp_json.get("choices", [])
            choice = choices[0] if choices else {}
            content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason")

            parsed = _parse_llm_batch_response(content, request.requirements, finish_reason=finish_reason)
            latency_ms = (time.monotonic() - t0) * 1000.0

            if not parsed or not parsed.verdicts:
                return ProviderResult(
                    provider=self.provider_name,
                    status=ProviderStatus.INVALID_RESPONSE,
                    raw_response=content,
                    usage=usage_stats,
                    latency_ms=latency_ms,
                    error_message="Groq response contained no valid verdicts.",
                )

            return ProviderResult(
                provider=self.provider_name,
                status=ProviderStatus.SUCCESS,
                data=parsed,
                raw_response=content,
                usage=usage_stats,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            resp_obj = getattr(exc, "response", None)

            if status_code == 429:
                await gate.record_429(estimated_tokens, response=resp_obj)
                breaker.record_failure("groq", status_code=429, is_permanent=False, error_msg=str(exc))
                status = ProviderStatus.RATE_LIMITED
            else:
                await gate.release_reservation(estimated_tokens)
                if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
                    breaker.record_failure("groq", status_code=408, is_permanent=False, error_msg=str(exc))
                    status = ProviderStatus.TIMEOUT
                elif status_code in {401, 403}:
                    breaker.record_failure("groq", status_code=status_code, is_permanent=True, error_msg=str(exc))
                    status = ProviderStatus.AUTH_FAILED
                elif status_code == 404:
                    breaker.record_failure("groq", status_code=404, is_permanent=True, error_msg=str(exc))
                    status = ProviderStatus.MODEL_NOT_FOUND
                elif status_code and status_code >= 500:
                    breaker.record_failure("groq", status_code=status_code, is_permanent=False, error_msg=str(exc))
                    status = ProviderStatus.SERVER_ERROR
                else:
                    breaker.record_failure("groq", status_code=status_code, is_permanent=False, error_msg=str(exc))
                    status = ProviderStatus.UNKNOWN_ERROR

            latency_ms = (time.monotonic() - t0) * 1000.0
            return ProviderResult(
                provider=self.provider_name,
                status=status,
                status_code=status_code,
                error_message=str(exc),
                latency_ms=latency_ms,
                is_retryable=(status in {ProviderStatus.RATE_LIMITED, ProviderStatus.TIMEOUT, ProviderStatus.SERVER_ERROR}),
            )


class CerebrasAdapter(BaseLLMAdapter):
    provider_name: str = "cerebras"
    _client: httpx.AsyncClient | None = None

    @classmethod
    def _get_client(cls, timeout: float) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(timeout=timeout)
        return cls._client

    @property
    def enabled(self) -> bool:
        return bool(
            _get_setting(self.settings, "ENABLE_HYBRID_MATCHING", True)
            and _get_setting(self.settings, "CEREBRAS_API_KEY", None)
        )

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        from app.services.matching_service import GroqMatchEvaluator
        evaluator = GroqMatchEvaluator(self.settings)
        payload = evaluator._payload(request.requirements, request.evidence, request.allowed_evidence)
        model_name = str(_get_setting(self.settings, "CEREBRAS_MODEL", "llama3.1-70b"))
        payload["model"] = model_name
        payload["max_tokens"] = min(
            int(_get_setting(self.settings, "CEREBRAS_MAX_COMPLETION_TOKENS", 4096)),
            max(1024, len(request.requirements) * 350 + 200),
        )
        return payload

    async def execute(self, request: LLMRequest, allow_retries: bool = False) -> ProviderResult:
        t0 = time.monotonic()
        if not self.enabled:
            return ProviderResult(
                provider=self.provider_name,
                status=ProviderStatus.DISABLED,
                error_message="Cerebras provider is disabled or CEREBRAS_API_KEY is not configured.",
                latency_ms=0.0,
            )

        from app.services.matching_service import (
            CerebrasTokenBudgetGate,
            GroqTokenBudgetGate,
            ProviderCircuitBreaker,
            _parse_llm_batch_response,
        )

        breaker = ProviderCircuitBreaker.get_breaker(self.settings)
        if not breaker.can_call("cerebras"):
            return ProviderResult(
                provider=self.provider_name,
                status=ProviderStatus.CIRCUIT_OPEN,
                error_message="Cerebras circuit breaker is open.",
                latency_ms=0.0,
            )

        payload = self.build_payload(request)
        gate = CerebrasTokenBudgetGate.get_gate(self.settings)
        groq_gate = GroqTokenBudgetGate.get_gate(self.settings)
        estimated_tokens = groq_gate.estimate_tokens(payload)

        has_budget = await gate.try_reserve(estimated_tokens)
        if not has_budget:
            return ProviderResult(
                provider=self.provider_name,
                status=ProviderStatus.BUDGET_EXHAUSTED,
                error_message="Cerebras token budget is exhausted.",
                latency_ms=(time.monotonic() - t0) * 1000.0,
                is_retryable=True,
            )

        timeout = float(_get_setting(self.settings, "CEREBRAS_TIMEOUT_SECONDS", 30.0))
        client = self._get_client(timeout)
        base_url = str(_get_setting(self.settings, "CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1")).rstrip("/")
        api_key = str(_get_setting(self.settings, "CEREBRAS_API_KEY", ""))

        try:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()

            resp_json = response.json()
            usage = resp_json.get("usage", {})
            prompt_toks = usage.get("prompt_tokens", 0)
            comp_toks = usage.get("completion_tokens", 0)
            tot_toks = usage.get("total_tokens") or (prompt_toks + comp_toks)
            usage_stats = {"prompt_tokens": prompt_toks, "completion_tokens": comp_toks, "total_tokens": tot_toks}

            await gate.record_response(estimated_tokens, response=response, actual_tokens=tot_toks)
            breaker.record_success("cerebras")

            choices = resp_json.get("choices", [])
            choice = choices[0] if choices else {}
            content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason")

            parsed = _parse_llm_batch_response(content, request.requirements, finish_reason=finish_reason)
            latency_ms = (time.monotonic() - t0) * 1000.0

            if not parsed or not parsed.verdicts:
                return ProviderResult(
                    provider=self.provider_name,
                    status=ProviderStatus.INVALID_RESPONSE,
                    raw_response=content,
                    usage=usage_stats,
                    latency_ms=latency_ms,
                    error_message="Cerebras response contained no valid verdicts.",
                )

            return ProviderResult(
                provider=self.provider_name,
                status=ProviderStatus.SUCCESS,
                data=parsed,
                raw_response=content,
                usage=usage_stats,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            await gate.release_reservation(estimated_tokens)
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            resp_body = None
            if hasattr(exc, "response") and exc.response is not None:
                try:
                    resp_body = exc.response.text
                except Exception:
                    pass

            if status_code == 402:
                # Permanent billing/quota failure on Cerebras -> fast-fail, mark circuit OPEN, never retry
                logger.critical(
                    "cerebras_provider_billing_error — payment required",
                    provider="cerebras",
                    status_code=402,
                    response_body=resp_body,
                )
                breaker.record_failure("cerebras", status_code=402, is_permanent=True, error_msg=str(exc))
                status = ProviderStatus.PAYMENT_REQUIRED
            elif status_code in {401, 403}:
                breaker.record_failure("cerebras", status_code=status_code, is_permanent=True, error_msg=str(exc))
                status = ProviderStatus.AUTH_FAILED
            elif status_code == 404:
                breaker.record_failure("cerebras", status_code=404, is_permanent=True, error_msg=str(exc))
                status = ProviderStatus.MODEL_NOT_FOUND
            elif status_code == 429:
                breaker.record_failure("cerebras", status_code=429, is_permanent=False, error_msg=str(exc))
                status = ProviderStatus.RATE_LIMITED
            elif status_code and status_code >= 500:
                breaker.record_failure("cerebras", status_code=status_code, is_permanent=False, error_msg=str(exc))
                status = ProviderStatus.SERVER_ERROR
            elif isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
                breaker.record_failure("cerebras", status_code=408, is_permanent=False, error_msg=str(exc))
                status = ProviderStatus.TIMEOUT
            else:
                breaker.record_failure("cerebras", status_code=status_code, is_permanent=False, error_msg=str(exc))
                status = ProviderStatus.UNKNOWN_ERROR

            latency_ms = (time.monotonic() - t0) * 1000.0
            return ProviderResult(
                provider=self.provider_name,
                status=status,
                status_code=status_code,
                error_message=str(exc),
                latency_ms=latency_ms,
                is_retryable=(status in {ProviderStatus.RATE_LIMITED, ProviderStatus.TIMEOUT, ProviderStatus.SERVER_ERROR}),
            )


class ProviderRouter:
    """
    Orchestrates decoupled multi-provider fallback.
    Primary: Groq.
    Fallback: Cerebras (immediate failover upon Groq provider error/exhaustion).
    """
    def __init__(
        self,
        settings: Settings | None = None,
        groq_adapter: BaseLLMAdapter | None = None,
        cerebras_adapter: BaseLLMAdapter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.groq = groq_adapter or GroqAdapter(self.settings)
        self.cerebras = cerebras_adapter or CerebrasAdapter(self.settings)

    async def route_and_evaluate(
        self, request: LLMRequest
    ) -> tuple[list[MatchVerdict], dict[str, Any]]:
        from app.services.matching_service import GroqMatchEvaluator, ProviderCircuitBreaker

        breaker = ProviderCircuitBreaker.get_breaker(self.settings)
        evaluator_validator = GroqMatchEvaluator(self.settings)

        telemetry: dict[str, Any] = {
            "resume_id": request.resume_id,
            "provider_selected": "none",
            "fallback_used": False,
            "fallback_reason": "none",
            "primary_error": None,
            "fallback_error": None,
            "actual_total_tokens": 0,
            "actual_input_tokens": 0,
            "actual_output_tokens": 0,
            "llm_duration_ms": 0.0,
            "circuit_skipped": [],
        }

        if not request.requirements:
            return [], telemetry

        start_time = time.monotonic()
        groq_can_call = self.groq.can_call(breaker)
        if not groq_can_call and self.groq.enabled:
            telemetry["circuit_skipped"].append("groq")

        selected_result: ProviderResult | None = None
        attempted_providers: list[str] = []

        # 1. Attempt Primary: Groq
        if groq_can_call:
            attempted_providers.append("groq")
            logger.info(
                "llm_evaluation_started",
                provider_selected="groq",
                resume_id=request.resume_id,
                requirements_count=len(request.requirements),
            )
            groq_res = await self.groq.execute(request, allow_retries=False)

            if groq_res.status.is_success and groq_res.data:
                selected_result = groq_res
                telemetry["provider_selected"] = "groq"
                logger.info(
                    "llm_evaluation_completed",
                    provider="groq",
                    fallback_used=False,
                    resume_id=request.resume_id,
                    duration_ms=round(groq_res.latency_ms, 2),
                )
            else:
                telemetry["primary_error"] = groq_res.status.value
                fallback_reason = f"groq_{groq_res.status.value}"
                telemetry["fallback_reason"] = fallback_reason

                logger.warning(
                    "llm_provider_failed",
                    provider="groq",
                    failure_type=groq_res.status.value,
                    fallback_provider="cerebras" if self.cerebras.can_call(breaker) else "none",
                    error=groq_res.error_message,
                    status_code=groq_res.status_code,
                    resume_id=request.resume_id,
                )

        # 2. Attempt Fallback: Cerebras (immediate takeover)
        if selected_result is None:
            cerebras_can_call = self.cerebras.can_call(breaker)
            if not cerebras_can_call and self.cerebras.enabled:
                telemetry["circuit_skipped"].append("cerebras")

            if cerebras_can_call:
                attempted_providers.append("cerebras")
                telemetry["provider_selected"] = "cerebras"
                telemetry["fallback_used"] = True

                logger.info(
                    "llm_fallback_to_cerebras_started",
                    provider_selected="cerebras",
                    reason=telemetry["fallback_reason"],
                    resume_id=request.resume_id,
                )
                cerebras_res = await self.cerebras.execute(request, allow_retries=False)

                if cerebras_res.status.is_success and cerebras_res.data:
                    selected_result = cerebras_res
                    logger.info(
                        "llm_evaluation_completed",
                        provider="cerebras",
                        fallback_used=True,
                        resume_id=request.resume_id,
                        duration_ms=round(cerebras_res.latency_ms, 2),
                    )
                else:
                    telemetry["fallback_error"] = cerebras_res.status.value
                    logger.error(
                        "llm_provider_failed",
                        provider="cerebras",
                        failure_type=cerebras_res.status.value,
                        error=cerebras_res.error_message,
                        status_code=cerebras_res.status_code,
                        resume_id=request.resume_id,
                    )

        total_duration_ms = (time.monotonic() - start_time) * 1000.0
        telemetry["llm_duration_ms"] = round(total_duration_ms, 2)

        # 3. Validation & Output
        if selected_result and selected_result.data:
            validated = evaluator_validator._validate(
                selected_result.data,
                request.requirements,
                request.evidence,
                allowed_evidence=request.allowed_evidence,
            )
            telemetry["actual_total_tokens"] = selected_result.usage.get("total_tokens", 0)
            telemetry["actual_input_tokens"] = selected_result.usage.get("prompt_tokens", 0)
            telemetry["actual_output_tokens"] = selected_result.usage.get("completion_tokens", 0)
            return validated, telemetry

        # 4. Both failed or unavailable -> Safe UNRESOLVED
        logger.warning(
            "llm_evaluation_unresolved",
            providers_attempted=",".join(attempted_providers) or "none",
            primary_error=telemetry["primary_error"],
            fallback_error=telemetry["fallback_error"],
            circuit_skipped=telemetry["circuit_skipped"],
            resume_id=request.resume_id,
        )
        return [], telemetry
