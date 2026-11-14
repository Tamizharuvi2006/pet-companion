import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

from app.services.openrouter_tts_service import OpenRouterTTSService
from app.services.tts_service import TTSAudioChunk


class UnusedFallback:
    async def synthesize(self, _text: str, **_options: object) -> str:
        raise AssertionError("Race path should use stream_audio")

    async def stream_audio(self, _text: str, **_options: object) -> AsyncIterator[TTSAudioChunk]:
        yield TTSAudioChunk(provider="edge", data=b"edge-first-bytes")


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
        assert first == TTSAudioChunk(provider="edge", data=b"edge-first-bytes")

        await stream.aclose()
        await service.close()
        assert loser_cancelled.is_set()

    asyncio.run(run())
