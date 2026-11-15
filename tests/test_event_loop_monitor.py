import asyncio
import time

from app.services.event_loop_monitor import (
    sample_event_loop_lag,
    sample_event_loop_profile,
)


async def measure_blocking_loop_lag_ms() -> float:
    stop = asyncio.Event()
    monitor = asyncio.create_task(sample_event_loop_lag(stop, interval_seconds=0.005))
    await asyncio.sleep(0.015)
    time.sleep(0.05)
    stop.set()
    samples = await monitor
    return max(samples, default=0.0)


async def measure_threaded_work_lag_ms() -> tuple[float, int]:
    stop = asyncio.Event()
    monitor = asyncio.create_task(sample_event_loop_lag(stop, interval_seconds=0.005))
    await asyncio.sleep(0.015)
    await asyncio.to_thread(time.sleep, 0.05)
    stop.set()
    samples = await monitor
    return max(samples, default=0.0), len(samples)


def test_loop_lag_probe_observes_a_blocked_event_loop() -> None:
    assert asyncio.run(measure_blocking_loop_lag_ms()) >= 20.0


def test_loop_lag_probe_keeps_sampling_while_work_runs_in_a_thread() -> None:
    max_lag_ms, sample_count = asyncio.run(measure_threaded_work_lag_ms())
    assert sample_count >= 3
    assert max_lag_ms < 50.0


def test_loop_profile_reports_blocking_lag_cpu_and_worker_activity() -> None:
    async def run():
        stop = asyncio.Event()
        monitor = asyncio.create_task(
            sample_event_loop_profile(stop, interval_seconds=0.005)
        )
        await asyncio.sleep(0.015)
        time.sleep(0.05)
        stop.set()
        return await monitor

    profile = asyncio.run(run())
    assert profile.max_lag_ms >= 20.0
    assert profile.samples >= 1
    assert profile.process_cpu_percent >= 0.0
    assert profile.max_active_threads >= 1
    assert profile.max_active_tasks >= 1


def test_loop_profile_stays_responsive_for_threaded_sleep() -> None:
    async def run():
        stop = asyncio.Event()
        monitor = asyncio.create_task(
            sample_event_loop_profile(stop, interval_seconds=0.005)
        )
        await asyncio.sleep(0.015)
        await asyncio.to_thread(time.sleep, 0.05)
        stop.set()
        return await monitor

    profile = asyncio.run(run())
    assert profile.samples >= 3
    assert profile.max_lag_ms < 50.0
    assert profile.max_active_threads >= 1
