import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from app.services import edge_tts_service
from app.services.event_loop_monitor import sample_event_loop_lag
from app.services.mp3_stream import first_valid_mp3_prefix, has_complete_mp3_frames


def _frame() -> bytes:
    # MPEG-1 Layer III, 128 kbps, 44.1 kHz, no padding (417 bytes per frame).
    return b"\xff\xfb\x90\x64" + bytes(413)


def test_edge_times_out_before_valid_prefix_and_releases_slot(monkeypatch, tmp_path) -> None:
    class StalledProvider:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def stream(self) -> AsyncIterator[dict[str, object]]:
            yield {"type": "audio", "data": _frame()}
            await asyncio.Event().wait()

    monkeypatch.setattr(edge_tts_service.edge_tts, "Communicate", StalledProvider)
    monkeypatch.setattr(edge_tts_service, "EDGE_FIRST_AUDIO_TIMEOUT_SECONDS", 0.02)

    async def run() -> None:
        slot = asyncio.Semaphore(1)
        settings = SimpleNamespace(tts_voice="test", audio_dir=tmp_path)
        service = edge_tts_service.EdgeTTSService(settings, slot)
        with pytest.raises(RuntimeError, match="timed out before playable audio"):
            await anext(service.stream_audio("Hello"))
        assert not slot.locked()

    asyncio.run(run())


def test_requires_two_complete_consecutive_mp3_frames() -> None:
    one_frame = _frame()
    assert not has_complete_mp3_frames(one_frame)
    assert has_complete_mp3_frames(one_frame + _frame())
    assert not has_complete_mp3_frames(b"edge-first-bytes" + one_frame)


def test_accepts_complete_frames_after_id3v2_tag() -> None:
    tag_body = b"Bella"
    tag = b"ID3\x04\x00\x00\x00\x00\x00\x05" + tag_body
    assert has_complete_mp3_frames(tag + _frame() + _frame())


def test_first_valid_prefix_buffers_split_frames_but_is_bounded() -> None:
    async def run() -> None:
        audio = _frame() + _frame() + _frame()

        async def pieces() -> AsyncIterator[bytes]:
            for start in range(0, len(audio), 73):
                yield audio[start : start + 73]

        prefix = await first_valid_mp3_prefix(pieces())
        assert prefix.startswith(b"\xff\xfb\x90\x64")
        assert has_complete_mp3_frames(prefix)
        assert len(prefix) == 73 * 12  # first network piece containing two full frames

    asyncio.run(run())


def test_truncated_or_non_mp3_provider_stream_is_rejected() -> None:
    async def run() -> None:
        async def truncated() -> AsyncIterator[bytes]:
            yield _frame()[:200]

        with pytest.raises(RuntimeError, match="before two complete MP3 frames"):
            await first_valid_mp3_prefix(truncated())

        async def too_long() -> AsyncIterator[bytes]:
            yield b"x" * 33

        with pytest.raises(RuntimeError, match="did not yield a valid MP3 prefix"):
            await first_valid_mp3_prefix(too_long(), max_probe_bytes=32)

    asyncio.run(run())


def test_malformed_prefix_scan_is_bounded_and_keeps_event_loop_responsive() -> None:
    async def run() -> tuple[float, int]:
        stop = asyncio.Event()
        monitor = asyncio.create_task(sample_event_loop_lag(stop, interval_seconds=0.005))

        async def invalid_chunks() -> AsyncIterator[bytes]:
            for _ in range(8):
                yield bytes(64 * 1024)
                await asyncio.sleep(0)

        with pytest.raises(RuntimeError, match="ended before two complete MP3 frames"):
            await first_valid_mp3_prefix(invalid_chunks())
        stop.set()
        samples = await monitor
        return max(samples, default=0.0), len(samples)

    max_lag_ms, sample_count = asyncio.run(run())
    assert sample_count >= 3
    assert max_lag_ms < 150.0
