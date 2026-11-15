import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

from app.services.openrouter_tts_service import OpenRouterTTSService
from app.services.mp3_stream import has_complete_mp3_frames
from app.services.tts_service import TTSAudioChunk


class UnusedFallback:
    async def synthesize(self, _text: str, **_options: object) -> str:
        raise AssertionError("Race path should use stream_audio")

    async def stream_audio(self, _text: str, **_options: object) -> AsyncIterator[TTSAudioChunk]:
        yield TTSAudioChunk(provider="edge", data=_valid_mp3())


def _valid_mp3() -> bytes:
    frame = b"\xff\xfb\x90\x64" + bytes(413)
    return frame + frame


def test_stream_race_returns_first_provider_bytes_and_cleans_loser() -> None:
    async def run() -> None:
        settings = SimpleNamespace(
            openrouter_tts_voice="af_bella",
            openrouter_tts_cute_voice="af_bella",
            openrouter_tts_enabled=True,
            openrouter_api_key="test-key",
            openrouter_tts_timeout_seconds=1.0,
            app_name="Bella test",
            audio_dir=Path("unused-test-audio"),
            tts_race_enabled=True,
            openrouter_tts_model="hexgrad/kokoro-82m",
        )
        service = OpenRouterTTSService(settings, UnusedFallback())  # type: ignore[arg-type]
        loser_cancelled = asyncio.Event()

        async def slow_kokoro(_text: str, _voice: str) -> AsyncIterator[bytes]:
            try:
                await asyncio.Event().wait()
                yield b"unreachable"
            finally:
                loser_cancelled.set()

        service._stream_kokoro = slow_kokoro  # type: ignore[method-assign]
        stream = service.stream_audio("hello")
        first = await asyncio.wait_for(anext(stream), timeout=0.5)
        assert first.provider == "edge"
        assert has_complete_mp3_frames(first.data)

        await stream.aclose()
        await service.close()
        assert loser_cancelled.is_set()

    asyncio.run(run())


def test_race_skips_fast_invalid_stream_and_selects_valid_provider() -> None:
    async def run() -> None:
        settings = SimpleNamespace(
            openrouter_tts_voice="af_bella",
            openrouter_tts_cute_voice="af_bella",
            openrouter_tts_enabled=True,
            openrouter_api_key="test-key",
            openrouter_tts_timeout_seconds=1.0,
            app_name="Bella test",
            audio_dir=Path("unused-test-audio"),
            tts_race_enabled=True,
            openrouter_tts_model="hexgrad/kokoro-82m",
        )

        class ValidFallback(UnusedFallback):
            async def stream_audio(self, _text: str, **_options: object) -> AsyncIterator[TTSAudioChunk]:
                yield TTSAudioChunk(provider="edge", data=b"\xff\xfb")
                yield TTSAudioChunk(provider="edge", data=_valid_mp3()[2:])

        service = OpenRouterTTSService(settings, ValidFallback())  # type: ignore[arg-type]

        async def invalid_fast(_text: str, _voice: str) -> AsyncIterator[bytes]:
            yield b"not an MP3 frame"

        service._stream_kokoro = invalid_fast  # type: ignore[method-assign]
        pieces = [chunk async for chunk in service.stream_audio("hello")]
        assert pieces
        assert pieces[0].provider == "edge"
        assert has_complete_mp3_frames(pieces[0].data)
        await service.close()

    asyncio.run(run())
