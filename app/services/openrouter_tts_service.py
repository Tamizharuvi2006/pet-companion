import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from time import perf_counter

import aiofiles
import httpx

from app.core.config import Settings
from app.services.edge_tts_service import EdgeTTSService
from app.services.tts_service import TTSAudioChunk
from app.services.voice_trace import mark_voice_stage
from app.services.request_limits import provider_slot
from app.services.mp3_stream import first_valid_mp3_prefix, has_complete_mp3_frames
from app.services.provider_budget import reserve_provider_call
from app.services.provider_budget import BOUNDED_FULL_TTS_MAX_INPUT_CHARS

logger = logging.getLogger(__name__)


class OpenRouterTTSService:
    """Kokoro speech with Edge TTS as a reliable no-config fallback."""

    def __init__(
        self,
        settings: Settings,
        fallback: EdgeTTSService,
        provider_semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._settings = settings
        self._fallback = fallback
        self._provider_semaphore = provider_semaphore
        self._audio_dir = settings.audio_dir
        self._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            # A spoken first sentence is latency-critical. Fall back to Edge
            # promptly instead of holding the whole voice turn for 60 seconds.
            timeout=settings.openrouter_tts_timeout_seconds,
            headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": settings.app_name,
            },
        )
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    async def load(self) -> None:
        """Kokoro is remote, so no startup model load is required."""

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> str:
        diagnostic_mode = getattr(self._settings, "voice_test_enabled", False)
        if diagnostic_mode and len(text) > BOUNDED_FULL_TTS_MAX_INPUT_CHARS:
            raise ValueError("Voice test TTS input exceeds the local safety limit")
        if diagnostic_mode:
            if (
                (voice is not None and voice != self._settings.openrouter_tts_voice)
                or rate is not None
                or pitch is not None
                or not self._settings.openrouter_tts_enabled
                or not self._settings.openrouter_api_key
            ):
                raise RuntimeError("Voice test mode requires Kokoro; Edge fallback is disabled")
            return await self._synthesize_with_kokoro(
                text, voice or self._settings.openrouter_tts_voice
            )
        # Keep named Edge voices/rate/pitch controls as a fallback-only feature.
        # Bella's normal and cute modes use Kokoro's two configured English voices.
        kokoro_voices = {
            self._settings.openrouter_tts_voice,
            self._settings.openrouter_tts_cute_voice,
        }
        if voice is not None and voice not in kokoro_voices:
            return await self._fallback.synthesize(text, voice=voice, rate=rate, pitch=pitch)
        if rate is not None or pitch is not None:
            return await self._fallback.synthesize(text, voice=voice, rate=rate, pitch=pitch)
        if not self._settings.openrouter_tts_enabled or not self._settings.openrouter_api_key:
            logger.info("Kokoro TTS unavailable; using Edge TTS fallback")
            return await self._fallback.synthesize(text)

        started = perf_counter()
        try:
            if self._settings.tts_race_enabled:
                return await self._synthesize_with_race(
                    text, voice or self._settings.openrouter_tts_voice, started
                )
            audio_url = await self._synthesize_with_kokoro(text, voice or self._settings.openrouter_tts_voice)
            logger.info("Kokoro TTS time: %.2fs", perf_counter() - started)
            return audio_url
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            logger.warning("Kokoro TTS failed; using Edge TTS fallback: %s", error)
            return await self._fallback.synthesize(text)

    async def stream_audio(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Stream provider MP3 bytes; voice-turn playback need not await a whole file."""
        diagnostic_mode = getattr(self._settings, "voice_test_enabled", False)
        if diagnostic_mode and len(text) > BOUNDED_FULL_TTS_MAX_INPUT_CHARS:
            raise ValueError("Voice test TTS input exceeds the local safety limit")
        kokoro_voices = {
            self._settings.openrouter_tts_voice,
            self._settings.openrouter_tts_cute_voice,
        }
        if diagnostic_mode and (
            (voice is not None and voice != self._settings.openrouter_tts_voice)
            or rate is not None
            or pitch is not None
            or not self._settings.openrouter_tts_enabled
            or not self._settings.openrouter_api_key
        ):
            raise RuntimeError("Voice test mode requires Kokoro; Edge fallback is disabled")
        if (
            (voice is not None and voice not in kokoro_voices)
            or rate is not None
            or pitch is not None
            or not self._settings.openrouter_tts_enabled
            or not self._settings.openrouter_api_key
        ):
            async for chunk in self._validated_edge_stream(
                text, voice=voice, rate=rate, pitch=pitch
            ):
                yield chunk
            return

        selected_voice = voice or self._settings.openrouter_tts_voice
        if self._settings.tts_race_enabled and not diagnostic_mode:
            async for chunk in self._stream_race(text, selected_voice):
                yield chunk
            return

        kokoro = self._stream_kokoro(text, selected_voice)
        try:
            first_chunk = await first_valid_mp3_prefix(kokoro)
        except asyncio.CancelledError:
            await kokoro.aclose()
            raise
        except (StopAsyncIteration, httpx.HTTPError, RuntimeError, ValueError) as error:
            await kokoro.aclose()
            if diagnostic_mode:
                raise RuntimeError("Diagnostic Kokoro stream failed; Edge fallback is disabled") from error
            logger.warning(
                "Kokoro stream failed before audio; using Edge fallback (%s)",
                type(error).__name__,
            )
            async for chunk in self._validated_edge_stream(text):
                yield chunk
            return
        mark_voice_stage(
            "tts_provider_first_audio_selected",
            provider="kokoro",
            bytes=len(first_chunk),
        )
        mark_voice_stage(
            "tts_provider_valid_mp3_prefix",
            provider="kokoro",
            bytes=len(first_chunk),
            minimum_frames=2,
        )
        yield TTSAudioChunk(provider="kokoro", data=first_chunk)
        try:
            async for data in kokoro:
                yield TTSAudioChunk(provider="kokoro", data=data)
        finally:
            await kokoro.aclose()

    async def _stream_race(
        self, text: str, voice: str
    ) -> AsyncIterator[TTSAudioChunk]:
        """Choose the first provider with two complete MP3 frames, not raw bytes."""
        started = perf_counter()
        streams: dict[str, AsyncIterator[bytes]] = {
            "kokoro": self._stream_kokoro(text, voice),
            "edge": self._stream_edge_bytes(text),
        }
        pending: dict[asyncio.Task[bytes], tuple[str, AsyncIterator[bytes]]] = {
            asyncio.create_task(first_valid_mp3_prefix(stream)): (provider, stream)
            for provider, stream in streams.items()
        }
        winner: str | None = None
        winner_stream: AsyncIterator[bytes] | None = None
        failures: list[str] = []
        try:
            while pending and winner is None:
                complete, _ = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                ordered = sorted(complete, key=lambda task: pending[task][0] != "kokoro")
                for task in ordered:
                    provider, stream = pending.pop(task)
                    try:
                        data = task.result()
                    except StopAsyncIteration:
                        failures.append(f"{provider}:empty")
                        await stream.aclose()
                        continue
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        failures.append(f"{provider}:{type(error).__name__}")
                        await stream.aclose()
                        continue
                    winner = provider
                    winner_stream = stream
                    mark_voice_stage(
                        "tts_winner_first_audio_bytes",
                        duration_seconds=perf_counter() - started,
                        provider=winner,
                        bytes=len(data),
                    )
                    mark_voice_stage(
                        "tts_provider_first_audio_selected",
                        provider=winner,
                        bytes=len(data),
                    )
                    mark_voice_stage(
                        "tts_provider_valid_mp3_prefix",
                        provider=winner,
                        bytes=len(data),
                        minimum_frames=2,
                    )
                    self._schedule_stream_cleanup(pending)
                    pending.clear()
                    yield TTSAudioChunk(provider=winner, data=data)
                    break

            if winner is None or winner_stream is None:
                raise RuntimeError("Both streaming TTS providers failed: " + ", ".join(failures))

            total_bytes = len(data)
            try:
                async for data in winner_stream:
                    total_bytes += len(data)
                    yield TTSAudioChunk(provider=winner, data=data)
            finally:
                await winner_stream.aclose()
            mark_voice_stage(
                "tts_winner_stream_complete",
                duration_seconds=perf_counter() - started,
                provider=winner,
                bytes=total_bytes,
            )
        finally:
            if pending:
                await self._cancel_and_cleanup(pending)

    async def _stream_kokoro(self, text: str, voice: str) -> AsyncIterator[bytes]:
        started = perf_counter()
        mark_voice_stage("kokoro_request_started", provider="kokoro")
        total_bytes = 0
        first_audio = True
        async with provider_slot(self._provider_semaphore):
            await reserve_provider_call(
                "kokoro_tts",
                required=getattr(self._settings, "voice_test_enabled", False),
            )
            async with self._client.stream(
                "POST",
                "/audio/speech",
                headers={"Authorization": f"Bearer {self._settings.openrouter_api_key}"},
                json={
                    "model": self._settings.openrouter_tts_model,
                    "input": text,
                    "voice": voice,
                    "response_format": "mp3",
                },
            ) as response:
                response.raise_for_status()
                async for data in response.aiter_bytes():
                    if not data:
                        continue
                    total_bytes += len(data)
                    if first_audio:
                        mark_voice_stage(
                            "kokoro_first_audio_bytes",
                            duration_seconds=perf_counter() - started,
                            provider="kokoro",
                            bytes=len(data),
                        )
                        first_audio = False
                    yield data
        if first_audio:
            raise RuntimeError("Kokoro returned empty audio")
        mark_voice_stage(
            "kokoro_stream_complete",
            duration_seconds=perf_counter() - started,
            provider="kokoro",
            bytes=total_bytes,
        )

    async def _stream_edge_bytes(self, text: str) -> AsyncIterator[bytes]:
        async for chunk in self._fallback.stream_audio(text):
            yield chunk.data

    async def _validated_edge_stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        stream = self._fallback.stream_audio(text, voice=voice, rate=rate, pitch=pitch)
        try:
            async def edge_bytes() -> AsyncIterator[bytes]:
                async for chunk in stream:
                    yield chunk.data

            prefix = await first_valid_mp3_prefix(edge_bytes())
        except BaseException:
            await stream.aclose()
            raise
        mark_voice_stage(
            "tts_provider_valid_mp3_prefix",
            provider="edge",
            bytes=len(prefix),
            minimum_frames=2,
        )
        mark_voice_stage(
            "tts_provider_first_audio_selected", provider="edge", bytes=len(prefix)
        )
        yield TTSAudioChunk(provider="edge", data=prefix)
        try:
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()

    async def _synthesize_with_race(self, text: str, voice: str, started: float) -> str:
        """Race a cute Kokoro voice against Edge so slow provider turns do not stall speech."""
        pending: dict[asyncio.Task[str], str] = {
            asyncio.create_task(self._synthesize_with_kokoro(text, voice)): "kokoro",
            asyncio.create_task(self._fallback.synthesize(text)): "edge",
        }
        failures: list[str] = []
        try:
            while pending:
                complete, _ = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                # If both complete in the same event-loop turn, keep the cute
                # Kokoro result rather than changing Bella's voice unnecessarily.
                ordered_complete = sorted(
                    complete, key=lambda task: pending[task] != "kokoro"
                )
                for task in ordered_complete:
                    provider = pending.pop(task)
                    try:
                        audio_url = task.result()
                    except Exception as error:
                        failures.append(f"{provider}: {type(error).__name__}")
                        continue

                    logger.info(
                        "TTS race winner selected=%s time: %.2fs",
                        provider,
                        perf_counter() - started,
                    )
                    mark_voice_stage(
                        "tts_race_winner_selected",
                        duration_seconds=perf_counter() - started,
                        provider=provider,
                    )
                    self._schedule_file_cleanup(pending)
                    return audio_url
        finally:
            await self._cancel_and_cleanup(pending)

        raise RuntimeError("Both TTS providers failed: " + ", ".join(failures))

    async def _cancel_and_cleanup(self, pending: dict[asyncio.Task[str], str]) -> None:
        """Stop the loser and remove a completed-but-unused audio file, if any."""
        tasks = tuple(pending)
        pending.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, str):
                await self._remove_audio_file(result)

    def _schedule_file_cleanup(self, pending: dict[asyncio.Task[str], str]) -> None:
        tasks = tuple(pending)
        pending.clear()
        if not tasks:
            return
        cleanup = asyncio.create_task(self._cleanup_files(tasks))
        self._track_cleanup(cleanup)

    async def _cleanup_files(self, tasks: tuple[asyncio.Task[str], ...]) -> None:
        started = perf_counter()
        for task in tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, str):
                await self._remove_audio_file(result)
        mark_voice_stage(
            "tts_race_loser_cleanup_complete",
            duration_seconds=perf_counter() - started,
        )

    def _schedule_stream_cleanup(
        self,
        pending: dict[asyncio.Task[bytes], tuple[str, AsyncIterator[bytes]]],
    ) -> None:
        if not pending:
            return
        losers = tuple(pending.items())
        cleanup = asyncio.create_task(self._cleanup_streams(losers))
        self._track_cleanup(cleanup)

    async def _cleanup_streams(
        self,
        losers: tuple[
            tuple[asyncio.Task[bytes], tuple[str, AsyncIterator[bytes]]], ...
        ],
    ) -> None:
        started = perf_counter()
        for task, _ in losers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*(task for task, _ in losers), return_exceptions=True)
        for _, (_, stream) in losers:
            with suppress(Exception):
                await stream.aclose()
        mark_voice_stage(
            "tts_race_loser_cleanup_complete",
            duration_seconds=perf_counter() - started,
        )

    def _track_cleanup(self, task: asyncio.Task[None]) -> None:
        self._cleanup_tasks.add(task)

        def completed(cleanup_task: asyncio.Task[None]) -> None:
            self._cleanup_tasks.discard(cleanup_task)
            if cleanup_task.cancelled():
                return
            error = cleanup_task.exception()
            if error is not None:
                logger.warning("TTS race loser cleanup failed: %s", type(error).__name__)

        task.add_done_callback(completed)

    async def _remove_audio_file(self, audio_url: str) -> None:
        filename = audio_url.removeprefix("/audio/")
        if filename == audio_url:
            return
        path = self._audio_dir / filename
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def _synthesize_with_kokoro(self, text: str, voice: str) -> str:
        async with provider_slot(self._provider_semaphore):
            await reserve_provider_call(
                "kokoro_tts",
                required=getattr(self._settings, "voice_test_enabled", False),
            )
            response = await self._client.post(
                "/audio/speech",
                headers={"Authorization": f"Bearer {self._settings.openrouter_api_key}"},
                json={
                    "model": self._settings.openrouter_tts_model,
                    "input": text,
                    "voice": voice,
                    "response_format": "mp3",
                },
            )
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("Kokoro returned empty audio")
        if not has_complete_mp3_frames(response.content):
            raise RuntimeError("Kokoro returned a truncated or invalid MP3 file")

        self._audio_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4()}.mp3"
        destination = self._audio_dir / filename
        try:
            async with aiofiles.open(destination, "wb") as output:
                await output.write(response.content)
        except BaseException:
            # A race loser can be cancelled while it is writing its result.
            with suppress(OSError):
                destination.unlink()
            raise
        return f"/audio/{filename}"

    async def close(self) -> None:
        cleanup_tasks = tuple(self._cleanup_tasks)
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        await self._client.aclose()
