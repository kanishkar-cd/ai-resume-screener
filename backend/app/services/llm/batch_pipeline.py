from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any
import httpx
from pydantic import BaseModel, Field
import structlog

from app.core.config import Settings, get_settings
from app.services.llm.key_pool import GroqKeyLease, GroqKeyPoolManager
from app.schemas.matching import (
    Evidence,
    MatchMethod,
    MatchStatus,
    MatchVerdict,
    Requirement,
    RequirementKind,
)

logger = structlog.get_logger(__name__)


class ResumeBatchContext(BaseModel):
    """Encapsulates the LLM evaluation context for a single resume."""
    resume_id: str
    requirements: list[Requirement]
    candidate_evidence: list[Evidence]
    allowed_evidence: dict[str, set[str]] = Field(default_factory=dict)


def group_into_batches(
    contexts: list[ResumeBatchContext], batch_size: int = 3
) -> list[list[ResumeBatchContext]]:
    """Partitions eligible resume contexts into batches of exactly batch_size (default 3)."""
    if not contexts:
        return []
    return [contexts[i : i + batch_size] for i in range(0, len(contexts), batch_size)]


def build_system_evaluation_prompt() -> str:
    """Returns the authoritative system evaluation prompt used across all LLM providers."""
    return (
        "You are evaluating candidate fit for job requirements across multiple candidate resumes.\n\n"
        "CRITICAL CONTEXT ISOLATION RULE:\n"
        "Evaluate EACH candidate resume INDEPENDENTLY. NEVER mix or cross-cite evidence between different resumes.\n"
        "Only cite evidence_ids that exist in THAT candidate's 'candidate_evidence'.\n\n"
        "EVALUATION INSTRUCTIONS:\n"
        "1. If a requirement bundles multiple sub-skills/duties, decompose it into atomic sub-claims in 'sub_claims'.\n"
        "2. For each atomic sub-claim, check candidate evidence for:\n"
        "   - 'direct' = explicit tool/skill/duty match\n"
        "   - 'adjacent' = similar tool, same pattern, related tech stack, or transferable duty\n"
        "   - 'none' = no evidence\n"
        "   Record in 'sub_claim_evidence' as list: [{\"claim\": \"...\", \"evidence_level\": \"direct|adjacent|none\", \"note\": \"...\"}].\n"
        "3. Score each requirement 0.0-1.0 as 'coverage_score' on a continuous scale:\n"
        "   - 1.0 = full direct evidence across all sub-claims\n"
        "   - 0.7-0.9 = most sub-claims directly evidenced, minor gaps\n"
        "   - 0.4-0.6 = partial (adjacent/transferable evidence or subset met)\n"
        "   - 0.1-0.3 = weak tangential mention only\n"
        "   - 0.0 = no relevant evidence\n"
        "4. Set 'status' to: 'MATCHED' (coverage>=0.7), 'PARTIALLY_MATCHED' (coverage 0.25-0.69), 'NO_MATCH' (coverage<0.25).\n"
        "5. Cite valid candidate evidence_ids from THAT candidate's evidence in 'evidence_ids'.\n\n"
        "OUTPUT FORMAT (Strict JSON only):\n"
        "{\n"
        "  \"results\": [\n"
        "    {\n"
        "      \"resume_id\": \"string\",\n"
        "      \"verdicts\": [\n"
        "        {\n"
        "          \"requirement_id\": \"string\",\n"
        "          \"status\": \"MATCHED|PARTIALLY_MATCHED|NO_MATCH\",\n"
        "          \"sub_claims\": [\"string\"],\n"
        "          \"sub_claim_evidence\": [{\"claim\": \"string\", \"evidence_level\": \"direct|adjacent|none\", \"note\": \"string\"}],\n"
        "          \"coverage_score\": 0.0,\n"
        "          \"importance\": \"critical|important|minor\",\n"
        "          \"evidence_ids\": [\"string\"],\n"
        "          \"reasoning\": \"1-2 sentence justification\"\n"
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )


def normalize_evidence_id(raw_id: str, valid_supplied_ids: set[str]) -> str | None:
    """Normalizes and maps raw LLM evidence citation to candidate allowed evidence ID."""
    if not raw_id or not isinstance(raw_id, str):
        return None
    clean = raw_id.strip(" \t\n\r[](){}<>\"'.,;:")
    if clean in valid_supplied_ids:
        return clean

    clean_lower = clean.casefold()
    for sid in valid_supplied_ids:
        if sid.casefold() == clean_lower:
            return sid

    normalized_form = re.sub(r"[\s_#-]+", ":", clean_lower)
    normalized_form = re.sub(r":+", ":", normalized_form)
    for sid in valid_supplied_ids:
        if sid.casefold() == normalized_form:
            return sid

    if clean.isdigit():
        candidates = [sid for sid in valid_supplied_ids if sid.endswith(f":{clean}")]
        if len(candidates) == 1:
            return candidates[0]

    return None


def validate_single_resume_verdicts(
    raw_verdicts: list[dict[str, Any]],
    ctx: ResumeBatchContext,
    settings: Settings | None = None,
) -> list[MatchVerdict]:
    """Validates evidence grounding, entity compatibility, and confidence thresholds for a single resume."""
    from app.services.matching_service import is_entity_compatible

    cfg = settings or get_settings()
    threshold = float(getattr(cfg, "HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD", 0.80))
    req_by_id = {r.requirement_id: r for r in ctx.requirements}
    ev_by_id = {e.evidence_id: e for e in ctx.candidate_evidence}
    result: list[MatchVerdict] = []
    seen_reqs: set[str] = set()

    for item in raw_verdicts:
        if not isinstance(item, dict):
            continue
        req_id = str(item.get("requirement_id", "")).strip()
        if not req_id or req_id not in req_by_id or req_id in seen_reqs:
            continue
        seen_reqs.add(req_id)
        req_obj = req_by_id[req_id]

        allowed_ids = ctx.allowed_evidence.get(req_id, set()) & set(ev_by_id.keys())
        raw_cited_ids = list(item.get("evidence_ids") or [])
        valid_cited_ids: list[str] = []

        for raw_id in raw_cited_ids:
            norm_id = normalize_evidence_id(raw_id, allowed_ids)
            if norm_id and norm_id not in valid_cited_ids:
                ev_item = ev_by_id.get(norm_id)
                if ev_item and not is_entity_compatible(req_obj.kind, ev_item.kind):
                    continue
                valid_cited_ids.append(norm_id)

        # If no raw citations supplied but candidate evidence was allowed, attach compatible evidence
        if not valid_cited_ids and not raw_cited_ids and allowed_ids:
            compatible = [
                sid for sid in allowed_ids
                if (ev := ev_by_id.get(sid)) and is_entity_compatible(req_obj.kind, ev.kind)
            ]
            if compatible:
                valid_cited_ids = compatible[:3]

        has_valid_evidence = bool(valid_cited_ids)
        raw_reasoning = str(item.get("reasoning", "") or "").strip()
        raw_reasoning_lower = raw_reasoning.lower()

        negation_phrases = (
            "no evidence", "none of the provided", "none of the candidate", "no candidate evidence",
            "does not mention", "doesn't mention", "no mention", "lacks ", "lacking ",
            "not mentioned", "no relevant evidence", "no direct or adjacent",
            "neither direct nor adjacent", "no experience mentioned", "no matching evidence",
            "no demonstrated experience", "unmet", "zero evidence", "no transferable evidence",
        )
        has_negation = any(phrase in raw_reasoning_lower for phrase in negation_phrases)
        sub_claim_evidence_val = item.get("sub_claim_evidence") or []
        all_subclaims_none = (
            bool(sub_claim_evidence_val)
            and all(isinstance(sc, dict) and sc.get("evidence_level") == "none" for sc in sub_claim_evidence_val)
        )

        raw_status_str = str(item.get("status", "")).upper()
        is_matched_raw = raw_status_str in {"MATCHED", "MATCH"}
        is_partial_raw = raw_status_str in {"PARTIALLY_MATCHED", "PARTIAL"}
        is_no_match_raw = raw_status_str in {"NO_MATCH", "UNMATCHED", "REJECTED"}

        raw_cov = item.get("coverage_score")
        if raw_cov is None:
            raw_cov = item.get("coverage")

        if raw_cov is not None:
            coverage_val = float(raw_cov)
        elif sub_claim_evidence_val:
            direct_cnt = sum(1 for sc in sub_claim_evidence_val if isinstance(sc, dict) and sc.get("evidence_level") == "direct")
            adj_cnt = sum(1 for sc in sub_claim_evidence_val if isinstance(sc, dict) and sc.get("evidence_level") == "adjacent")
            tot = len(sub_claim_evidence_val)
            coverage_val = (direct_cnt * 1.0 + adj_cnt * 0.5) / tot if tot > 0 else 0.0
        else:
            coverage_val = 1.0 if is_matched_raw else (0.5 if is_partial_raw else 0.0)

        # Negation Guard
        if has_negation or all_subclaims_none:
            coverage_val = 0.0
            is_matched_raw = False
            is_partial_raw = False
            is_no_match_raw = True

        confirmed = (coverage_val >= 0.25 or is_matched_raw or is_partial_raw) and not is_no_match_raw
        raw_conf = item.get("confidence")
        item_confidence = float(raw_conf) if (raw_conf is not None and float(raw_conf) > 0.0) else 1.0

        if confirmed and not has_valid_evidence:
            status = MatchStatus.NO_MATCH
            method = MatchMethod.LLM_REJECTED
            coverage_val = 0.0
            reasoning = f"(Rejected: No valid candidate evidence cited). {raw_reasoning}".strip()
        elif confirmed and raw_conf is not None and float(raw_conf) > 0.0 and item_confidence < threshold:
            status = MatchStatus.NO_MATCH
            method = MatchMethod.LLM_REJECTED
            coverage_val = 0.0
            reasoning = f"LLM match verdict rejected due to low confidence ({item_confidence:.2f} < threshold {threshold:.2f})."
        elif confirmed and coverage_val > 0.0:
            if coverage_val >= 0.7 or (is_matched_raw and coverage_val >= 0.5):
                status = MatchStatus.MATCHED
            else:
                status = MatchStatus.PARTIALLY_MATCHED
            method = MatchMethod.LLM_CONFIRMED
            reasoning = raw_reasoning or "LLM confirmed requirement match from candidate evidence."
        elif is_no_match_raw:
            status = MatchStatus.NO_MATCH
            method = MatchMethod.LLM_REJECTED
            reasoning = raw_reasoning or "LLM verified requirement is unmet."
        else:
            status = MatchStatus.NO_MATCH
            method = MatchMethod.LLM_REJECTED
            reasoning = raw_reasoning or "Requirement unmet."

        importance_val = str(item.get("importance") or getattr(req_obj, "importance", "important") or "important").lower()
        if importance_val not in {"critical", "important", "minor"}:
            importance_val = getattr(req_obj, "importance", "important")

        result.append(MatchVerdict(
            requirement_id=req_id,
            requirement_text=req_obj.text,
            kind=req_obj.kind,
            status=status,
            confidence=item_confidence if confirmed else 0.0,
            evidence_ids=sorted(valid_cited_ids) if valid_cited_ids else [],
            reasoning=reasoning.strip(),
            method=method,
            coverage=coverage_val,
            coverage_score=coverage_val,
            importance=importance_val,
            sub_claims=item.get("sub_claims") or [],
            sub_claim_evidence=sub_claim_evidence_val,
        ))

    return result


def parse_and_validate_multi_resume_response(
    content: str,
    batch: list[ResumeBatchContext],
    settings: Settings | None = None,
) -> dict[str, list[MatchVerdict]]:
    """Parses multi-resume JSON payload and validates verdicts against each resume's isolated context."""
    if not content or not isinstance(content, str):
        return {}

    data: dict[str, Any] = {}
    try:
        data = json.loads(content.strip())
    except Exception:
        # Fallback regex search for JSON block
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = {}

    if not data:
        return {}

    context_by_id = {ctx.resume_id: ctx for ctx in batch}
    if isinstance(data, list):
        results_list = data
    else:
        results_list = data.get("results")
        if not isinstance(results_list, list):
            # If the response returned a top-level verdicts list directly for 1 resume
            if "verdicts" in data and len(batch) == 1:
                results_list = [{"resume_id": batch[0].resume_id, "verdicts": data["verdicts"]}]
            else:
                return {}

    output_map: dict[str, list[MatchVerdict]] = {}
    for r_item in results_list:
        if not isinstance(r_item, dict):
            continue
        r_id = str(r_item.get("resume_id", "")).strip()
        if not r_id or r_id not in context_by_id:
            if len(batch) == 1:
                r_id = batch[0].resume_id
            else:
                continue

        ctx = context_by_id[r_id]
        raw_verdicts = r_item.get("verdicts", [])
        if isinstance(raw_verdicts, list):
            validated = validate_single_resume_verdicts(raw_verdicts, ctx, settings=settings)
            output_map[r_id] = validated

    return output_map


def build_failed_verdicts(
    contexts: list[ResumeBatchContext],
    failure_reason: str = "AI Review Unavailable",
    settings: Settings | None = None,
) -> dict[str, list[MatchVerdict]]:
    """Constructs graceful EVALUATION_FAILED verdicts for unrecoverable batch/resume failures."""
    output = {}
    for ctx in contexts:
        v_list = []
        for r in ctx.requirements:
            v_list.append(MatchVerdict(
                requirement_id=r.requirement_id,
                requirement_text=r.text,
                kind=r.kind,
                status=MatchStatus.EVALUATION_FAILED,
                confidence=0.0,
                evidence_ids=[],
                reasoning=f"AI evaluation could not be completed for this requirement ({failure_reason}).",
                method=MatchMethod.EVALUATION_FAILED,
                coverage=0.0,
                coverage_score=0.0,
                importance=getattr(r, "importance", "important"),
                sub_claims=[r.text],
                sub_claim_evidence=[{"claim": r.text, "evidence_level": "none", "note": "Evaluation failed."}],
            ))
        output[ctx.resume_id] = v_list
    return output


class GroqBatchExecutor:
    """
    Executes post-deterministic multi-resume evaluation against Groq as primary provider.
    Supports isolated retries of only failed/missing resumes, with optional OpenRouter fallback.
    """
    _client: httpx.AsyncClient | None = None

    def __init__(
        self,
        settings: Settings | None = None,
        key_pool: GroqKeyPoolManager | None = None,
        openrouter_executor: Any | None = None,
        max_retries: int = 2,
    ) -> None:
        self.settings = settings or get_settings()
        self.key_pool = key_pool or GroqKeyPoolManager(self.settings)
        self.openrouter_executor = openrouter_executor
        self.max_retries = max_retries

    @classmethod
    def _get_client(cls, timeout: float) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(timeout=timeout)
        return cls._client

    @property
    def enabled(self) -> bool:
        has_keys = bool(
            getattr(self.settings, "groq_is_configured", False)
            or getattr(self.settings, "groq_keys", None)
            or getattr(self.settings, "GROQ_API_KEY", None)
            or (hasattr(self, "key_pool") and self.key_pool.total_keys > 0)
        )
        return bool(getattr(self.settings, "ENABLE_HYBRID_MATCHING", True) and has_keys)

    def build_payload(self, batch: list[ResumeBatchContext]) -> dict[str, Any]:
        """Constructs a structured multi-resume prompt payload with isolated contexts."""
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
        model = getattr(self.settings, "GROQ_MODEL", "openai/gpt-oss-20b")
        max_output_tokens = int(getattr(self.settings, "GROQ_MAX_COMPLETION_TOKENS", 4096))
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

    async def execute_batch_with_retry(
        self,
        batch: list[ResumeBatchContext],
        max_retries: int | None = None,
    ) -> dict[str, list[MatchVerdict]]:
        """
        Executes a batch of up to 3 resumes against Groq.
        Uses GroqKeyPoolManager for fair key selection and per-key health tracking.
        If any individual resume fails, retries only the failed work on Groq.
        If Groq cannot complete the batch, falls back to OpenRouter for unresolved resumes.
        """
        if not batch:
            return {}

        successful_results: dict[str, list[MatchVerdict]] = {}
        pending_batch = list(batch)

        if not self.enabled:
            logger.warning("groq_batch_executor_disabled_or_no_api_key")
            # Groq is not configured/enabled; check if OpenRouter fallback is available
            fallback_exec = self._get_fallback_executor()
            if fallback_exec and fallback_exec.enabled:
                logger.info("groq_disabled_using_openrouter_fallback", batch_size=len(batch))
                return await fallback_exec.execute_batch_with_retry(batch)
            return self._build_failed_verdicts(batch, failure_reason="GROQ_DISABLED_OR_NO_API_KEY")

        effective_max_retries = max_retries if max_retries is not None else self.max_retries
        attempts = 0
        total_attempts = max(1, effective_max_retries + 1)
        used_failed_key_ids: set[str] = set()

        while pending_batch and attempts < total_attempts:
            attempts += 1
            batch_resume_ids = [ctx.resume_id for ctx in pending_batch]
            t0 = time.monotonic()

            logger.info(
                "groq_batch_request_started",
                batch_size=len(pending_batch),
                resume_ids=batch_resume_ids,
                attempt=attempts,
                max_attempts=total_attempts,
            )

            try:
                parsed_results, failure_code, used_key_id = await self._send_groq_request(
                    pending_batch, exclude_key_ids=used_failed_key_ids
                )
                duration_ms = (time.monotonic() - t0) * 1000.0

                if parsed_results:
                    failed_in_attempt: list[ResumeBatchContext] = []
                    for ctx in pending_batch:
                        if ctx.resume_id in parsed_results and parsed_results[ctx.resume_id]:
                            successful_results[ctx.resume_id] = parsed_results[ctx.resume_id]
                        else:
                            failed_in_attempt.append(ctx)

                    logger.info(
                        "groq_batch_request_completed",
                        batch_size=len(pending_batch),
                        success_count=len(pending_batch) - len(failed_in_attempt),
                        failed_count=len(failed_in_attempt),
                        duration_ms=round(duration_ms, 2),
                        attempt=attempts,
                        key_id=used_key_id,
                    )

                    # Only retry the failed subset
                    pending_batch = failed_in_attempt
                    used_failed_key_ids.clear()
                else:
                    if used_key_id:
                        used_failed_key_ids.add(used_key_id)

                    logger.warning(
                        "groq_batch_request_failed_attempt",
                        attempt=attempts,
                        failure_reason=failure_code,
                        duration_ms=round(duration_ms, 2),
                        key_id=used_key_id,
                    )
                    if failure_code == "GROQ_ALL_KEYS_UNAVAILABLE":
                        # All keys are disabled, in cooldown, or out of budget; break to fallback
                        break

                    # If rate limited on a key and no other key available, backoff briefly
                    if failure_code == "GROQ_HTTP_429" and attempts < total_attempts:
                        await asyncio.sleep(0.5)

            except Exception as exc:
                duration_ms = (time.monotonic() - t0) * 1000.0
                err_type = type(exc).__name__
                logger.error(
                    "groq_batch_request_exception",
                    attempt=attempts,
                    error_type=err_type,
                    error=str(exc),
                    duration_ms=round(duration_ms, 2),
                )
                if attempts < total_attempts:
                    await asyncio.sleep(0.5)

        # If any resumes remain unresolved on Groq, attempt OpenRouter fallback for ONLY those resumes
        if pending_batch:
            fallback_exec = self._get_fallback_executor()
            if fallback_exec and fallback_exec.enabled:
                logger.warning(
                    "groq_batch_exhausted_fallback_to_openrouter",
                    unresolved_count=len(pending_batch),
                    resume_ids=[c.resume_id for c in pending_batch],
                )
                fallback_results = await fallback_exec.execute_batch_with_retry(pending_batch)
                for r_id, v_list in fallback_results.items():
                    successful_results[r_id] = v_list
                pending_batch = [ctx for ctx in pending_batch if ctx.resume_id not in successful_results]

        # For any resumes that remain uncompleted after all providers, mark as EVALUATION_FAILED
        if pending_batch:
            failed_verdicts = self._build_failed_verdicts(
                pending_batch,
                failure_reason="AI Review Unavailable — provider failure or timeout",
            )
            for r_id, v_list in failed_verdicts.items():
                if r_id not in successful_results:
                    successful_results[r_id] = v_list

        return successful_results

    def _get_fallback_executor(self) -> Any | None:
        """Retrieves or lazily initializes the OpenRouter fallback executor."""
        if self.openrouter_executor is not None:
            return self.openrouter_executor
        try:
            from app.services.llm.openrouter_client import OpenRouterBatchExecutor
            self.openrouter_executor = OpenRouterBatchExecutor(self.settings)
            return self.openrouter_executor
        except Exception:
            return None

    async def _call_groq_api(
        self, payload: dict[str, Any], timeout_sec: float, api_key: str | None = None
    ) -> str:
        """Invokes Groq chat completion API with the selected key and returns response text content."""
        client = self._get_client(timeout_sec)
        base_url = str(getattr(self.settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")).rstrip("/")
        resolved_key = api_key or str(getattr(self.settings, "primary_groq_api_key", None) or getattr(self.settings, "GROQ_API_KEY", "") or "")
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {resolved_key}"},
            json=payload,
            timeout=timeout_sec,
        )
        response.raise_for_status()
        resp_json = response.json()
        self._last_response_usage = resp_json.get("usage", {})
        choices = resp_json.get("choices", [])
        choice = choices[0] if choices else {}
        return choice.get("message", {}).get("content", "")

    async def _send_groq_request(
        self,
        batch: list[ResumeBatchContext],
        exclude_key_ids: set[str] | None = None,
    ) -> tuple[dict[str, list[MatchVerdict]] | None, str | None, str | None]:
        """Sends HTTP request to Groq using key from pool, parses multi-resume JSON response, and validates per resume."""
        import inspect
        from app.services.matching_service import GroqTokenBudgetGate, ProviderCircuitBreaker

        breaker = ProviderCircuitBreaker.get_breaker(self.settings)
        if not breaker.can_call("groq"):
            return None, "GROQ_CIRCUIT_OPEN", None

        payload = self.build_payload(batch)
        gate = GroqTokenBudgetGate.get_gate(self.settings)
        estimated_tokens = gate.estimate_tokens(payload)

        lease = await self.key_pool.acquire_key(
            estimated_tokens=estimated_tokens,
            exclude_key_ids=exclude_key_ids,
        )
        if lease is None:
            pool_status = self.key_pool.get_pool_status()
            if pool_status["available_count"] == 0 and pool_status["cooldown_count"] == 0 and pool_status["disabled_count"] > 0:
                breaker.record_failure("groq", is_permanent=True, error_msg="All Groq keys are disabled")
            return None, "GROQ_ALL_KEYS_UNAVAILABLE", None

        timeout_sec = float(getattr(self.settings, "GROQ_TIMEOUT_SECONDS", 30.0))

        try:
            fn = getattr(self._call_groq_api, "side_effect", None) or self._call_groq_api
            sig = inspect.signature(fn)
            accepts_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if accepts_kw or len(sig.parameters) >= 3 or "api_key" in sig.parameters:
                content = await self._call_groq_api(payload, timeout_sec, api_key=lease.api_key)
            else:
                content = await self._call_groq_api(payload, timeout_sec)

            actual_tokens = None
            if hasattr(self, "_last_response_usage") and isinstance(self._last_response_usage, dict):
                actual_tokens = self._last_response_usage.get("total_tokens")

            await self.key_pool.mark_success(
                lease.key_id,
                estimated_tokens=estimated_tokens,
                actual_tokens=actual_tokens,
            )
            breaker.record_success("groq")

        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            resp_obj = getattr(exc, "response", None)

            if status_code == 429:
                await gate.record_429(estimated_tokens, response=resp_obj)
                await self.key_pool.mark_failure(
                    lease.key_id,
                    error_type="GROQ_HTTP_429",
                    status_code=429,
                    is_permanent=False,
                    estimated_tokens=estimated_tokens,
                )
                pool_status = self.key_pool.get_pool_status()
                if pool_status["available_count"] == 0:
                    breaker.record_failure("groq", status_code=429, is_permanent=False, error_msg=str(exc))
                return None, "GROQ_HTTP_429", lease.key_id
            else:
                if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
                    await self.key_pool.mark_failure(
                        lease.key_id,
                        error_type="GROQ_TIMEOUT",
                        status_code=408,
                        is_permanent=False,
                        estimated_tokens=estimated_tokens,
                    )
                    pool_status = self.key_pool.get_pool_status()
                    if pool_status["available_count"] == 0:
                        breaker.record_failure("groq", status_code=408, is_permanent=False, error_msg=str(exc))
                    return None, "GROQ_TIMEOUT", lease.key_id
                elif status_code in {401, 403}:
                    await self.key_pool.mark_failure(
                        lease.key_id,
                        error_type="GROQ_AUTH_FAILED",
                        status_code=status_code,
                        is_permanent=True,
                        estimated_tokens=estimated_tokens,
                    )
                    pool_status = self.key_pool.get_pool_status()
                    if pool_status["available_count"] == 0:
                        breaker.record_failure("groq", status_code=status_code, is_permanent=True, error_msg=str(exc))
                    return None, "GROQ_AUTH_FAILED", lease.key_id
                elif status_code and status_code >= 500:
                    await self.key_pool.mark_failure(
                        lease.key_id,
                        error_type=f"GROQ_HTTP_{status_code}",
                        status_code=status_code,
                        is_permanent=False,
                        estimated_tokens=estimated_tokens,
                    )
                    pool_status = self.key_pool.get_pool_status()
                    if pool_status["available_count"] == 0:
                        breaker.record_failure("groq", status_code=status_code, is_permanent=False, error_msg=str(exc))
                    return None, f"GROQ_HTTP_{status_code}", lease.key_id
                else:
                    await self.key_pool.mark_failure(
                        lease.key_id,
                        error_type=f"GROQ_ERROR_{type(exc).__name__}",
                        status_code=status_code,
                        is_permanent=False,
                        estimated_tokens=estimated_tokens,
                    )
                    pool_status = self.key_pool.get_pool_status()
                    if pool_status["available_count"] == 0:
                        breaker.record_failure("groq", status_code=status_code, is_permanent=False, error_msg=str(exc))
                    return None, f"GROQ_ERROR_{type(exc).__name__}", lease.key_id

        # Parse structured multi-resume results
        parsed_results = self._parse_and_validate_multi_resume_response(content, batch)
        return parsed_results, None, lease.key_id

    def _parse_and_validate_multi_resume_response(
        self, content: str, batch: list[ResumeBatchContext]
    ) -> dict[str, list[MatchVerdict]]:
        return parse_and_validate_multi_resume_response(content, batch, settings=self.settings)

    @staticmethod
    def _normalize_evidence_id(raw_id: str, valid_supplied_ids: set[str]) -> str | None:
        return normalize_evidence_id(raw_id, valid_supplied_ids)

    def _validate_single_resume_verdicts(
        self, raw_verdicts: list[dict[str, Any]], ctx: ResumeBatchContext
    ) -> list[MatchVerdict]:
        return validate_single_resume_verdicts(raw_verdicts, ctx, settings=self.settings)

    def _build_failed_verdicts(
        self, contexts: list[ResumeBatchContext], failure_reason: str = "AI Review Unavailable"
    ) -> dict[str, list[MatchVerdict]]:
        return build_failed_verdicts(contexts, failure_reason=failure_reason, settings=self.settings)


class PostDeterministicPipeline:
    """
    Orchestrates post-deterministic multi-resume batching and parallel execution.
    1. Batches eligible resumes into groups of exactly 3.
    2. Runs batches in parallel with bounded concurrency.
    3. Primary execution on Groq with key pool rotation and retries.
    4. Automatic fallback to OpenRouter if Groq is exhausted/unavailable.
    5. Maps results back to each resume deterministically.
    """
    def __init__(
        self,
        settings: Settings | None = None,
        executor: GroqBatchExecutor | None = None,
        key_pool: GroqKeyPoolManager | None = None,
        openrouter_executor: Any | None = None,
        max_concurrency: int = 3,
        max_retries: int = 2,
    ) -> None:
        self.settings = settings or get_settings()
        self.max_concurrency = max_concurrency
        self.key_pool = key_pool or (executor.key_pool if executor else GroqKeyPoolManager(self.settings))
        
        if openrouter_executor is None:
            try:
                from app.services.llm.openrouter_client import OpenRouterBatchExecutor
                self.openrouter_executor = OpenRouterBatchExecutor(self.settings)
            except Exception:
                self.openrouter_executor = None
        else:
            self.openrouter_executor = openrouter_executor

        self.executor = executor or GroqBatchExecutor(
            self.settings,
            key_pool=self.key_pool,
            openrouter_executor=self.openrouter_executor,
            max_retries=max_retries,
        )

    async def execute_parallel(
        self,
        contexts: list[ResumeBatchContext],
        batch_size: int = 3,
        max_concurrency: int | None = None,
    ) -> dict[str, list[MatchVerdict]]:
        """
        Partitions contexts into batches of 3 and executes them concurrently using asyncio.gather.
        """
        if not contexts:
            return {}

        concurrency = self.max_concurrency if max_concurrency is None else max_concurrency
        batches = group_into_batches(contexts, batch_size=batch_size)
        semaphore = asyncio.Semaphore(concurrency)

        logger.info(
            "post_deterministic_pipeline_started",
            total_eligible_resumes=len(contexts),
            batch_count=len(batches),
            batch_size=batch_size,
            max_concurrency=concurrency,
        )

        async def _run_batch(batch_idx: int, batch_items: list[ResumeBatchContext]) -> dict[str, list[MatchVerdict]]:
            async with semaphore:
                logger.info(
                    "batch_execution_acquired_semaphore",
                    batch_index=batch_idx,
                    batch_size=len(batch_items),
                    resume_ids=[c.resume_id for c in batch_items],
                )
                return await self.executor.execute_batch_with_retry(batch_items)

        batch_tasks = [_run_batch(idx, b) for idx, b in enumerate(batches)]
        results_list = await asyncio.gather(*batch_tasks)

        merged_results: dict[str, list[MatchVerdict]] = {}
        for b_res in results_list:
            merged_results.update(b_res)

        logger.info(
            "post_deterministic_pipeline_completed",
            total_evaluated=len(merged_results),
            batch_count=len(batches),
        )
        return merged_results
