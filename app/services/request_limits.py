"""Small bounded in-process rate and concurrency controls."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from time import monotonic
from typing import AsyncIterator


class CapacityExceeded(RuntimeError):
    """Raised when an application capacity gate is full."""


class SlidingWindowRateLimiter:
    def __init__(self, max_keys: int = 10_000) -> None:
        self._max_keys = max_keys
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        now = monotonic()
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)
            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            while len(self._buckets) > self._max_keys:
                self._buckets.popitem(last=False)
            return True


class CapacityGate:
    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._active = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            if self._active >= self._capacity:
                return False
            self._active += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        if not await self.acquire():
            raise CapacityExceeded("Bella is at capacity; try again shortly")
        try:
            yield
        finally:
            await self.release()


@asynccontextmanager
async def provider_slot(semaphore: asyncio.Semaphore | None) -> AsyncIterator[None]:
    if semaphore is None:
        yield
        return
    async with semaphore:
        yield
