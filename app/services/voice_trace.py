"""Monotonic, privacy-safe timing markers for one voice turn."""

from __future__ import annotations

import contextvars
import logging
import uuid
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)

_voice_trace: contextvars.ContextVar[VoiceTrace | None] = contextvars.ContextVar(
    "bella_voice_trace", default=None
)
_SAFE_FIELDS = frozenset({"provider", "chunk", "bytes", "frame", "words", "status"})


@dataclass(slots=True)
class VoiceTrace:
    """A per-turn trace; offsets use only this process's monotonic clock."""

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=perf_counter)

    def mark(
        self,
        stage: str,
        *,
        duration_seconds: float | None = None,
        **fields: Any,
    ) -> None:
        """Write only stage metadata, never user speech, prompts, URLs, or secrets."""
        safe = [
            f"{key}={_format_field(value)}"
            for key, value in fields.items()
            if key in _SAFE_FIELDS and isinstance(value, (str, int, float, bool))
        ]
        duration = (
            f" duration_ms={duration_seconds * 1000:.1f}"
            if duration_seconds is not None
            else ""
        )
        suffix = f" {' '.join(safe)}" if safe else ""
        logger.info(
            "voice_timing trace_id=%s stage=%s offset_ms=%.1f%s%s",
            self.trace_id,
            stage,
            (perf_counter() - self.started_at) * 1000,
            duration,
            suffix,
        )


def _format_field(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value.replace(" ", "_")[:48]
    return str(value)


def bind_voice_trace(trace: VoiceTrace) -> contextvars.Token[VoiceTrace | None]:
    return _voice_trace.set(trace)


def reset_voice_trace(token: contextvars.Token[VoiceTrace | None]) -> None:
    _voice_trace.reset(token)


def mark_voice_stage(
    stage: str,
    *,
    duration_seconds: float | None = None,
    **fields: Any,
) -> None:
    trace = _voice_trace.get()
    if trace is not None:
        trace.mark(stage, duration_seconds=duration_seconds, **fields)


def current_voice_trace_id() -> str | None:
    trace = _voice_trace.get()
    return trace.trace_id if trace is not None else None
