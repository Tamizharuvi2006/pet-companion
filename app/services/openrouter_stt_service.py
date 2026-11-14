import asyncio
import base64
import logging
from pathlib import Path
from time import perf_counter

import httpx

from app.core.config import Settings
from app.services.whisper_service import WhisperService

logger = logging.getLogger(__name__)


class OpenRouterSTTService:
    """Cloud final transcription with a preloaded local Whisper fallback."""

    def __init__(self, settings: Settings, fallback: WhisperService) -> None:
        self._settings = settings
        self._fallback = fallback
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
        await self._fallback.load()

    async def transcribe(self, audio_path: Path, *, interim: bool = False) -> str:
        # Calling a paid remote STT endpoint for every 250 ms interim update would
        # add latency and cost. Tiny Whisper remains the responsive interim layer.
        if interim:
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
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            logger.warning(
                "OpenRouter STT model=%s failed; using Faster-Whisper fallback: %s",
                self._settings.openrouter_stt_model,
                error,
            )
            return await self._fallback.transcribe(audio_path)

    async def _transcribe_with_provider(self, audio_path: Path) -> str:
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

        response = await self._client.post(
            "/audio/transcriptions",
            headers={"Authorization": f"Bearer {self._settings.openrouter_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("The cloud STT provider returned an empty transcript")
        return text.strip()

    async def close(self) -> None:
        await self._client.aclose()
