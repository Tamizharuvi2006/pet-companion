"""Per-turn provider-call caps for the bounded local voice diagnostic mode."""

from __future__ import annotations

import asyncio
import contextvars
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

logger = logging.getLogger(__name__)

DIAGNOSTIC_PROVIDER_LIMITS = {
    "openrouter_stt": 1,
    "openrouter_chat": 1,
    "kokoro_tts": 1,
    "edge_tts": 0,
}

BOUNDED_FULL_VOICE_PROVIDER_LIMITS = {
    "openrouter_stt": 1,
    "openrouter_chat": 1,
    "kokoro_tts": 3,
    "edge_tts": 0,
}

# Defensive application cap for each Kokoro input in bounded acceptance mode.
# This is intentionally a local safety limit, not a claim about provider limits.
BOUNDED_FULL_TTS_MAX_INPUT_CHARS = 2_000


class ProviderBudgetError(RuntimeError):
    """A provider attempt was refused by the diagnostic budget."""


@dataclass(slots=True)
class ProviderCallBudget:
    """Atomic attempted-request counters shared by all tasks in one turn."""

    limits: dict[str, int] = field(
        default_factory=lambda: dict(DIAGNOSTIC_PROVIDER_LIMITS)
    )
    _attempted: dict[str, int] = field(default_factory=dict, init=False)
    _denied: dict[str, int] = field(default_factory=dict, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def reserve(self, provider: str) -> None:
        """Reserve one request immediately before dispatch; reservations never refund."""
        async with self._lock:
            limit = self.limits.get(provider, 0)
            attempted = self._attempted.get(provider, 0)
            if attempted >= limit:
                self._denied[provider] = self._denied.get(provider, 0) + 1
                raise ProviderBudgetError(
                    f"Diagnostic provider budget exhausted for {provider} ({limit} allowed)"
                )
            self._attempted[provider] = attempted + 1

    async def snapshot(self) -> dict[str, dict[str, int]]:
        async with self._lock:
            providers = self.limits.keys() | self._attempted.keys() | self._denied.keys()
            return {
                provider: {
                    "attempted": self._attempted.get(provider, 0),
                    "denied": self._denied.get(provider, 0),
                    "limit": self.limits.get(provider, 0),
                }
                for provider in sorted(providers)
            }


_current_budget: contextvars.ContextVar[ProviderCallBudget | None] = (
    contextvars.ContextVar("bella_provider_call_budget", default=None)
)


@asynccontextmanager
async def provider_budget_scope(
    enabled: bool | str,
) -> AsyncIterator[ProviderCallBudget | None]:
    """Bind a fresh budget to this task and any child tasks it starts."""
    if not enabled or enabled == "disabled":
        yield None
        return
    limits = (
        BOUNDED_FULL_VOICE_PROVIDER_LIMITS
        if enabled == "bounded_full_voice_test"
        else DIAGNOSTIC_PROVIDER_LIMITS
    )
    budget = ProviderCallBudget(limits=dict(limits))
    token = _current_budget.set(budget)
    try:
        yield budget
    finally:
        _current_budget.reset(token)


async def reserve_provider_call(provider: str, *, required: bool = False) -> None:
    """Enforce a bound budget, failing closed when diagnostic mode lacks one."""
    budget = _current_budget.get()
    if budget is None:
        if required:
            raise ProviderBudgetError(
                f"Diagnostic provider budget is missing for {provider}"
            )
        return
    await budget.reserve(provider)


async def log_budget_summary(
    budget: ProviderCallBudget | None, *, trace_id: str | None = None
) -> None:
    if budget is None:
        return
    summary = await budget.snapshot()
    logger.info("voice_provider_budget trace_id=%s counts=%s", trace_id or "http", summary)
