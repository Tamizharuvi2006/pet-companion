import asyncio
import base64
import logging
from pathlib import Path
from time import perf_counter

import httpx

from app.core.config import Settings
from app.services.whisper_service import WhisperService
from app.services.provider_budget import ProviderBudgetError, reserve_provider_call
from app.services.request_limits import provider_slot
from app.services.voice_trace import mark_voice_stage

logger = logging.getLogger(__name__)


class OpenRouterSTTService:
    """Cloud final transcription with a preloaded local Whisper fallback."""

    def __init__(
        self,
        settings: Settings,
        fallback: WhisperService,
        provider_semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._settings = settings
        self._fallback = fallback
        self._provider_semaphore = provider_semaphore
        self._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            timeout=settings.openrouter_timeout_seconds,
            headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": settings.app_name,
            },
        )

    async def load(self) -> None:
        """Keep the local models warm so a provider failure has no cold start."""
        if self._settings.whisper_preload_enabled:
            await self._fallback.load()

    async def transcribe(self, audio_path: Path, *, interim: bool = False) -> str:
        # Calling a paid remote STT endpoint for every 250 ms interim update would
        # add latency and cost. Tiny Whisper remains the responsive interim layer.
        if interim:
            if not self._settings.whisper_interim_enabled:
                return ""
            return await self._fallback.transcribe(audio_path, interim=True)

        if not self._settings.openrouter_stt_enabled or not self._settings.openrouter_api_key:
            logger.info("OpenRouter STT unavailable; using Faster-Whisper final fallback")
            return await self._fallback.transcribe(audio_path)

        started = perf_counter()
        try:
            text = await self._transcribe_with_provider(audio_path)
            logger.info(
                "OpenRouter STT model=%s time: %.2fs",
                self._settings.openrouter_stt_model,
                perf_counter() - started,
            )
            return text
        except ProviderBudgetError:
            raise
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            logger.warning(
                "OpenRouter STT model=%s failed; using Faster-Whisper fallback: %s",
                self._settings.openrouter_stt_model,
                error,
            )
            return await self._fallback.transcribe(audio_path)

    async def _transcribe_with_provider(self, audio_path: Path) -> str:
        preparation_started = perf_counter()
        audio_data = await asyncio.to_thread(audio_path.read_bytes)
        if not audio_data:
            raise RuntimeError("The audio recording is empty")

        audio_format = audio_path.suffix.lstrip(".").lower() or "webm"
        payload: dict[str, object] = {
            "model": self._settings.openrouter_stt_model,
            "input_audio": {
                "data": base64.b64encode(audio_data).decode("ascii"),
                "format": audio_format,
            },
        }
        if self._settings.whisper_language:
            payload["language"] = self._settings.whisper_language
        mark_voice_stage(
            "stt_request_prepared",
            duration_seconds=perf_counter() - preparation_started,
            provider_model=self._settings.openrouter_stt_model,
            bytes=len(audio_data),
        )

        slot_wait_started = perf_counter()
        async with provider_slot(self._provider_semaphore):
            mark_voice_stage(
                "stt_provider_slot_acquired",
                duration_seconds=perf_counter() - slot_wait_started,
            )
            await reserve_provider_call(
                "openrouter_stt",
                required=self._settings.voice_test_enabled,
            )
            request_started = perf_counter()
            mark_voice_stage(
                "stt_http_request_started",
                provider_model=self._settings.openrouter_stt_model,
            )
            response = await self._client.post(
                "/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._settings.openrouter_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            mark_voice_stage(
                "stt_http_response_received",
                duration_seconds=perf_counter() - request_started,
                provider_model=self._settings.openrouter_stt_model,
            )
            parse_started = perf_counter()
            body = response.json()
        mark_voice_stage(
            "stt_response_parsed",
            duration_seconds=perf_counter() - parse_started,
        )
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("The cloud STT provider returned an empty transcript")
        return text.strip()

    async def close(self) -> None:
        await self._client.aclose()
