"""Small opt-in event-loop lag sampler used only during a diagnostic voice turn."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from time import process_time


@dataclass(frozen=True, slots=True)
class EventLoopProfile:
    max_lag_ms: float
    max_lag_offset_ms: float
    average_lag_ms: float
    samples: int
    process_cpu_percent: float
    max_active_threads: int
    max_active_tasks: int


async def sample_event_loop_lag(
    stop: asyncio.Event, *, interval_seconds: float = 0.05
) -> list[float]:
    """Return scheduling-delay samples in milliseconds until ``stop`` is set."""
    loop = asyncio.get_running_loop()
    expected = loop.time() + interval_seconds
    samples: list[float] = []
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            now = loop.time()
            samples.append(max(0.0, now - expected) * 1000)
            expected = now + interval_seconds
    return samples


async def sample_event_loop_profile(
    stop: asyncio.Event, *, interval_seconds: float = 0.05
) -> EventLoopProfile:
    """Collect low-overhead lag, process CPU, thread and task telemetry."""
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    cpu_started_at = process_time()
    lag_sum_ms = 0.0
    max_lag_ms = 0.0
    max_lag_offset_ms = 0.0
    sample_count = 0
    max_threads = threading.active_count()
    max_tasks = len(asyncio.all_tasks(loop))

    while not stop.is_set():
        expected = loop.time() + interval_seconds
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            now = loop.time()
            lag_ms = max(0.0, now - expected) * 1000
            lag_sum_ms += lag_ms
            if lag_ms > max_lag_ms:
                max_lag_ms = lag_ms
                max_lag_offset_ms = (now - started_at) * 1000
            sample_count += 1
            max_threads = max(max_threads, threading.active_count())
            max_tasks = max(max_tasks, len(asyncio.all_tasks(loop)))

    elapsed = max(loop.time() - started_at, 0.000001)
    cpu_seconds = max(0.0, process_time() - cpu_started_at)
    return EventLoopProfile(
        max_lag_ms=max_lag_ms,
        max_lag_offset_ms=max_lag_offset_ms,
        average_lag_ms=lag_sum_ms / sample_count if sample_count else 0.0,
        samples=sample_count,
        process_cpu_percent=cpu_seconds / elapsed * 100,
        max_active_threads=max_threads,
        max_active_tasks=max_tasks,
    )
