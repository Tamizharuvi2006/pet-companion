"""Single-use, process-wide latch for a bounded diagnostic acceptance session."""

from __future__ import annotations

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


class DiagnosticSessionConsumedError(RuntimeError):
    """Raised when a request tries to reuse a consumed diagnostic session."""


class DiagnosticSessionLatch:
    """Allow one diagnostic request across all HTTP and WebSocket clients.

    The latch is initialized with the ASGI app at startup and is never reset in
    place. A new diagnostic session requires an explicit server restart.
    """

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.session_id = uuid.uuid4().hex[:12] if enabled else None
        self._claimed = False
        self._accepted_source: str | None = None
        self._rejected_attempts = 0
        self._lock = asyncio.Lock()

    async def claim(self, source: str) -> None:
        """Atomically consume the session; errors and cancellations never refund it."""
        if not self.enabled:
            return
        async with self._lock:
            if self._claimed:
                self._rejected_attempts += 1
                logger.warning(
                    "voice_diagnostic_session_rejected session_id=%s source=%s rejected=%s",
                    self.session_id,
                    source,
                    self._rejected_attempts,
                )
                raise DiagnosticSessionConsumedError(
                    "The one-shot diagnostic session has already been used; restart Bella to initialize a new test session."
                )
            self._claimed = True
            self._accepted_source = source
            logger.info(
                "voice_diagnostic_session_claimed session_id=%s source=%s",
                self.session_id,
                source,
            )

    async def snapshot(self) -> dict[str, str | int | bool | None]:
        """Return safe latch metadata for tests and local diagnostics."""
        async with self._lock:
            return {
                "enabled": self.enabled,
                "session_id": self.session_id,
                "claimed": self._claimed,
                "accepted_source": self._accepted_source,
                "rejected_attempts": self._rejected_attempts,
            }
