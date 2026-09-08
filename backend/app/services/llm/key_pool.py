from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any
import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class GroqKeyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    COOLDOWN = "COOLDOWN"
    DISABLED = "DISABLED"


@dataclass
class GroqKeyEntry:
    key_id: str
    api_key: str
    status: GroqKeyStatus = GroqKeyStatus.AVAILABLE
    token_budget: int = 7000
    reserved_in_flight: int = 0
    usage_history: list[tuple[float, int]] = field(default_factory=list)
    total_tokens_used: int = 0
    available_at: float = 0.0
    failure_count: int = 0
    permanent_failures: int = 0
    success_count: int = 0
    last_used: float = 0.0
    last_error: str | None = None


@dataclass(frozen=True)
class GroqKeyLease:
    key_id: str
    api_key: str
    estimated_tokens: int = 0


class GroqKeyPoolManager:
    """
    Manages a pool of Groq API keys with thread-safe / async-safe fair round-robin selection,
    independent per-key token budget accounting, health tracking (AVAILABLE, COOLDOWN, DISABLED),
    and cooldown recovery.
    Never exposes raw API keys in logs.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        keys: list[str] | None = None,
        cooldown_seconds: float | None = None,
        token_budget_per_key: int | None = None,
        window_seconds: float = 60.0,
    ) -> None:
        self.settings = settings or get_settings()
        self._custom_keys = keys
        self._custom_cooldown = cooldown_seconds
        self._custom_budget = token_budget_per_key
        self.window_seconds = window_seconds
        self._lock = asyncio.Lock()
        self._index = 0
        self._entries: list[GroqKeyEntry] = []
        self._init_pool()

    @property
    def cooldown_seconds(self) -> float:
        if self._custom_cooldown is not None:
            return float(self._custom_cooldown)
        return float(getattr(self.settings, "GROQ_KEY_COOLDOWN_SECONDS", 60.0))

    @property
    def default_key_budget(self) -> int:
        if self._custom_budget is not None:
            return int(self._custom_budget)
        val = getattr(self.settings, "GROQ_KEY_TOKEN_BUDGET", None)
        if val is not None:
            return int(val)
        tpm = getattr(self.settings, "GROQ_TPM_LIMIT", 8000)
        margin = getattr(self.settings, "GROQ_TPM_SAFETY_MARGIN", 0.125)
        return int(tpm * (1.0 - margin))

    @property
    def total_keys(self) -> int:
        return len(self._entries)

    def get_available_tokens(self, entry: GroqKeyEntry, now: float | None = None) -> int:
        """Calculates currently available tokens for an entry in its rolling window minus reserved tokens."""
        if now is None:
            now = time.monotonic()
        entry.usage_history = [(ts, tok) for ts, tok in entry.usage_history if now - ts < self.window_seconds]
        window_used = sum(tok for _, tok in entry.usage_history)
        return max(0, entry.token_budget - window_used - entry.reserved_in_flight)

    def _init_pool(self) -> None:
        """Discovers and normalizes Groq keys from configuration or explicit keys."""
        raw_keys: list[str] = []
        if self._custom_keys is not None:
            raw_keys = self._custom_keys
        else:
            configured = getattr(self.settings, "groq_keys", None)
            if configured:
                raw_keys = list(configured)
            else:
                single_key = getattr(self.settings, "GROQ_API_KEY", None)
                if single_key:
                    raw_keys = [single_key]

        # Filter empty / whitespace and deduplicate preserving order
        unique_keys: list[str] = []
        for k in raw_keys:
            if k and isinstance(k, str):
                cleaned = k.strip()
                if cleaned and cleaned not in unique_keys:
                    unique_keys.append(cleaned)

        budget = self.default_key_budget
        self._entries = [
            GroqKeyEntry(
                key_id=f"groq_key_{i+1}",
                api_key=key_val,
                status=GroqKeyStatus.AVAILABLE,
                token_budget=budget,
                usage_history=[],
            )
            for i, key_val in enumerate(unique_keys)
        ]
        self._index = 0

    async def acquire_key(
        self,
        estimated_tokens: int = 0,
        exclude_key_ids: set[str] | None = None,
    ) -> GroqKeyLease | None:
        """
        Acquires an available Groq key lease in round-robin order that has sufficient token budget.
        Recovers keys whose cooldown has expired.
        Atomically reserves estimated_tokens on the selected key.
        Returns None if no healthy keys with sufficient budget are currently available.
        """
        async with self._lock:
            if not self._entries:
                return None

            now = time.monotonic()
            # Recover expired cooldowns
            for entry in self._entries:
                if entry.status == GroqKeyStatus.COOLDOWN and now >= entry.available_at:
                    entry.status = GroqKeyStatus.AVAILABLE
                    entry.available_at = 0.0
                    logger.info(
                        "groq_key_recovered_from_cooldown",
                        key_id=entry.key_id,
                    )

            # Find candidate entries: AVAILABLE, not excluded, and have sufficient budget
            candidates = [
                e for e in self._entries
                if e.status == GroqKeyStatus.AVAILABLE
                and (not exclude_key_ids or e.key_id not in exclude_key_ids)
                and self.get_available_tokens(e, now) >= estimated_tokens
            ]

            # If all matching candidates were in exclude_key_ids, check without exclude filter
            if not candidates and exclude_key_ids:
                candidates = [
                    e for e in self._entries
                    if e.status == GroqKeyStatus.AVAILABLE
                    and self.get_available_tokens(e, now) >= estimated_tokens
                ]

            if not candidates:
                exhausted = [
                    e for e in self._entries
                    if e.status == GroqKeyStatus.AVAILABLE
                    and self.get_available_tokens(e, now) < estimated_tokens
                ]
                active_cooldowns = [e for e in self._entries if e.status == GroqKeyStatus.COOLDOWN]
                disabled_keys = [e for e in self._entries if e.status == GroqKeyStatus.DISABLED]
                logger.warning(
                    "groq_all_keys_unavailable_or_budget_exhausted",
                    total_keys=len(self._entries),
                    budget_exhausted_count=len(exhausted),
                    cooldown_count=len(active_cooldowns),
                    disabled_count=len(disabled_keys),
                    requested_tokens=estimated_tokens,
                )
                return None

            # Round-robin selection based on total entries pointer
            selected_entry = None
            total_entries = len(self._entries)
            for step in range(total_entries):
                candidate_idx = (self._index + step) % total_entries
                entry = self._entries[candidate_idx]
                if entry in candidates:
                    selected_entry = entry
                    self._index = (candidate_idx + 1) % total_entries
                    break

            if selected_entry is None:
                selected_entry = candidates[0]
                self._index = (self._index + 1) % total_entries

            # Atomically reserve in-flight tokens
            selected_entry.reserved_in_flight += estimated_tokens
            selected_entry.last_used = now
            remaining_after = self.get_available_tokens(selected_entry, now)

            logger.info(
                "groq_key_selected",
                key_id=selected_entry.key_id,
                status=selected_entry.status.value,
                reserved_tokens=estimated_tokens,
                remaining_tokens=remaining_after,
            )
            return GroqKeyLease(
                key_id=selected_entry.key_id,
                api_key=selected_entry.api_key,
                estimated_tokens=estimated_tokens,
            )

    async def mark_success(
        self,
        key_id: str,
        estimated_tokens: int = 0,
        actual_tokens: int | None = None,
        response: Any | None = None,
    ) -> None:
        """
        Marks successful API interaction for the given key, releases in-flight reservation,
        and records actual/estimated tokens in the key's rolling window.
        """
        async with self._lock:
            for entry in self._entries:
                if entry.key_id == key_id:
                    now = time.monotonic()
                    entry.reserved_in_flight = max(0, entry.reserved_in_flight - estimated_tokens)
                    tokens_consumed = actual_tokens if actual_tokens is not None else estimated_tokens
                    if tokens_consumed > 0:
                        entry.usage_history.append((now, tokens_consumed))
                        entry.total_tokens_used += tokens_consumed

                    if entry.status != GroqKeyStatus.DISABLED:
                        entry.status = GroqKeyStatus.AVAILABLE
                        entry.failure_count = 0
                        entry.success_count += 1
                        entry.last_error = None
                        logger.info(
                            "groq_key_success",
                            key_id=key_id,
                            tokens_consumed=tokens_consumed,
                            remaining_tokens=self.get_available_tokens(entry, now),
                        )
                    break

    async def mark_failure(
        self,
        key_id: str,
        error_type: str,
        status_code: int | None = None,
        is_permanent: bool = False,
        estimated_tokens: int = 0,
        cooldown_seconds: float | None = None,
    ) -> None:
        """
        Releases reserved tokens on failure and transitions key to COOLDOWN or DISABLED.
        - 401/403 or is_permanent -> DISABLED
        - 429/408/5xx/network error -> COOLDOWN
        """
        async with self._lock:
            for entry in self._entries:
                if entry.key_id == key_id:
                    now = time.monotonic()
                    entry.reserved_in_flight = max(0, entry.reserved_in_flight - estimated_tokens)
                    entry.failure_count += 1
                    entry.last_error = error_type
                    entry.last_used = now

                    if is_permanent or status_code in (401, 403):
                        entry.status = GroqKeyStatus.DISABLED
                        entry.permanent_failures += 1
                        logger.warning(
                            "groq_key_disabled",
                            key_id=key_id,
                            status_code=status_code,
                            error_type=error_type,
                            total_failures=entry.failure_count,
                        )
                    else:
                        cd = cooldown_seconds if cooldown_seconds is not None else self.cooldown_seconds
                        entry.status = GroqKeyStatus.COOLDOWN
                        entry.available_at = now + cd
                        logger.warning(
                            "groq_key_cooldown",
                            key_id=key_id,
                            status_code=status_code,
                            error_type=error_type,
                            cooldown_seconds=cd,
                            total_failures=entry.failure_count,
                        )
                    break

    async def release_reservation(self, key_id: str, estimated_tokens: int) -> None:
        """Releases in-flight reservation without marking success or failure."""
        async with self._lock:
            for entry in self._entries:
                if entry.key_id == key_id:
                    entry.reserved_in_flight = max(0, entry.reserved_in_flight - estimated_tokens)
                    break

    def get_pool_status(self) -> dict[str, Any]:
        """Returns safe status metadata and per-key budget statistics."""
        now = time.monotonic()
        available = 0
        cooldown = 0
        disabled = 0
        keys_summary = []

        for e in self._entries:
            eff_status = e.status
            if eff_status == GroqKeyStatus.COOLDOWN and now >= e.available_at:
                eff_status = GroqKeyStatus.AVAILABLE

            avail_toks = self.get_available_tokens(e, now)

            if eff_status == GroqKeyStatus.AVAILABLE:
                available += 1
            elif eff_status == GroqKeyStatus.COOLDOWN:
                cooldown += 1
            elif eff_status == GroqKeyStatus.DISABLED:
                disabled += 1

            window_used = sum(tok for ts, tok in e.usage_history if now - ts < self.window_seconds)

            keys_summary.append({
                "key_id": e.key_id,
                "status": eff_status.value,
                "token_budget": e.token_budget,
                "reserved_in_flight": e.reserved_in_flight,
                "window_tokens_used": window_used,
                "remaining_tokens": avail_toks,
                "total_tokens_used": e.total_tokens_used,
                "failure_count": e.failure_count,
                "success_count": e.success_count,
                "cooldown_remaining_sec": max(0.0, round(e.available_at - now, 1)) if eff_status == GroqKeyStatus.COOLDOWN else 0.0,
            })

        return {
            "total_keys": len(self._entries),
            "available_count": available,
            "cooldown_count": cooldown,
            "disabled_count": disabled,
            "keys": keys_summary,
        }

    async def reset_pool(self) -> None:
        """Resets all keys to AVAILABLE status and clears usage histories."""
        async with self._lock:
            for entry in self._entries:
                entry.status = GroqKeyStatus.AVAILABLE
                entry.available_at = 0.0
                entry.failure_count = 0
                entry.permanent_failures = 0
                entry.reserved_in_flight = 0
                entry.usage_history.clear()
                entry.total_tokens_used = 0
                entry.last_error = None
            self._index = 0
