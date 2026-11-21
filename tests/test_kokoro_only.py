import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.openrouter_tts_service import OpenRouterTTSService


class ForbiddenEdge:
    async def synthesize(self, *args, **kwargs):
        raise AssertionError("Edge must never be called")

    async def stream_audio(self, *args, **kwargs):
        raise AssertionError("Edge must never be called")
        yield


def test_kokoro_failure_never_calls_edge_even_with_legacy_race_flag():
    async def run():
        settings = SimpleNamespace(openrouter_tts_voice="af_bella", openrouter_tts_cute_voice="af_bella",
            openrouter_tts_enabled=True, openrouter_api_key="fake", openrouter_tts_timeout_seconds=8,
            app_name="test", audio_dir=Path("unused"), tts_race_enabled=True)
        service = OpenRouterTTSService(settings, ForbiddenEdge())

        async def failed(*args):
            raise httpx.ReadTimeout("offline timeout")
            yield

        service._stream_kokoro = failed
        try:
            with pytest.raises(RuntimeError, match="no backup provider"):
                await anext(service.stream_audio("Hello there."))
        finally:
            await service.close()

    asyncio.run(run())
