import asyncio
import logging
import uuid
from contextlib import aclosing
from pathlib import Path
from time import perf_counter
from collections.abc import AsyncIterator

import aiofiles
import edge_tts

from app.core.config import Settings
from app.services.provider_budget import reserve_provider_call
from app.services.provider_budget import ProviderBudgetError
from app.services.tts_service import TTSAudioChunk
from app.services.voice_trace import mark_voice_stage
from app.services.request_limits import provider_slot
from app.services.mp3_stream import first_valid_mp3_prefix

logger = logging.getLogger(__name__)
EDGE_FIRST_AUDIO_TIMEOUT_SECONDS = 5.0


class EdgeTTSService:
    def __init__(
        self, settings: Settings, provider_semaphore: asyncio.Semaphore | None = None
    ) -> None:
        self._settings = settings
        self._voice = settings.tts_voice
        self._audio_dir = settings.audio_dir
        self._provider_semaphore = provider_semaphore

    async def load(self) -> None:
        """Edge TTS has no model that needs local startup work."""

    async def close(self) -> None:
        """Edge TTS has no persistent client to close."""

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> str:
        self._audio_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4()}.mp3"
        output = self._audio_dir / filename
        started = perf_counter()
        try:
            async with aiofiles.open(output, "wb") as audio_file:
                async for chunk in self.stream_audio(
                    text, voice=voice, rate=rate, pitch=pitch
                ):
                    await audio_file.write(chunk.data)
        except BaseException as error:
            await asyncio.to_thread(output.unlink, missing_ok=True)
            if isinstance(error, asyncio.CancelledError):
                raise
            logger.exception("Text-to-speech failed")
            raise RuntimeError("Could not synthesize speech") from error
        logger.info("TTS time: %.2fs", perf_counter() - started)
        return f"/audio/{filename}"

    async def stream_audio(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Yield Edge's MP3 data events instead of waiting for Communicate.save."""
        started = perf_counter()
        mark_voice_stage("edge_request_started", provider="edge")
        total_bytes = 0
        first_audio = True
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice or self._voice,
            rate=rate or "+0%",
            pitch=pitch or "+0Hz",
        )
        async def encoded_audio() -> AsyncIterator[bytes]:
            nonlocal total_bytes, first_audio
            try:
                async with provider_slot(self._provider_semaphore):
                    await reserve_provider_call(
                        "edge_tts",
                        required=getattr(self._settings, "voice_test_enabled", False),
                    )
                    async for event in communicate.stream():
                        if event.get("type") != "audio":
                            continue
                        data = event.get("data")
                        if not isinstance(data, bytes) or not data:
                            continue
                        total_bytes += len(data)
                        if first_audio:
                            mark_voice_stage(
                                "edge_first_audio_bytes",
                                duration_seconds=perf_counter() - started,
                                provider="edge",
                                bytes=len(data),
                            )
                            first_audio = False
                        yield data
            except asyncio.CancelledError:
                mark_voice_stage("edge_stream_cancelled", provider="edge", bytes=total_bytes)
                raise
            except ProviderBudgetError:
                raise
            except Exception as error:
                logger.exception("Edge TTS stream failed")
                raise RuntimeError("Could not synthesize speech") from error
            if first_audio:
                raise RuntimeError("Edge TTS returned no audio")
            mark_voice_stage(
                "edge_stream_complete",
                duration_seconds=perf_counter() - started,
                provider="edge",
                bytes=total_bytes,
            )

        async with aclosing(encoded_audio()) as encoded:
            try:
                async with asyncio.timeout(EDGE_FIRST_AUDIO_TIMEOUT_SECONDS):
                    prefix = await first_valid_mp3_prefix(encoded)
            except TimeoutError as error:
                logger.warning("Edge TTS timed out waiting for a valid MP3 prefix")
                raise RuntimeError("Edge TTS timed out before playable audio") from error
            mark_voice_stage(
                "tts_provider_valid_mp3_prefix",
                provider="edge",
                bytes=len(prefix),
                minimum_frames=2,
            )
            yield TTSAudioChunk(provider="edge", data=prefix)
            async for data in encoded:
                yield TTSAudioChunk(provider="edge", data=data)
