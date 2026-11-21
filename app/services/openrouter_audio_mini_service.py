"""Primary OpenRouter GPT Audio Mini path for streamed text and PCM16 audio.

This adapter requests reply text plus audio from one OpenRouter chat stream and
forwards decoded audio bytes as soon as complete base64/PCM sample frames exist.
The prior STT -> text chat -> Kokoro cascade remains selectable for comparison.
"""

import asyncio
import base64
import binascii
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.services.provider_budget import reserve_provider_call
from app.services.request_limits import provider_slot

logger = logging.getLogger(__name__)
AudioSink = Callable[[bytes], Awaitable[None]]


class OpenRouterAudioMiniService:
    """Creates isolated GPT Audio Mini turns; it does not replace baseline AI/TTS."""

    def __init__(self, settings: Settings, semaphore: asyncio.Semaphore | None = None):
        self.settings = settings
        self.semaphore = semaphore
        self.client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            timeout=settings.openrouter_timeout_seconds,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key or ''}",
                "Content-Type": "application/json",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def prepare_audio(self, path: Path) -> str:
        """Convert one finalized browser WebM capture to bounded 16 kHz mono WAV."""
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-v", "error", "-i", str(path),
            "-t", str(self.settings.max_ws_recording_seconds + 1),
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            audio, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode != 0 or not audio:
            raise RuntimeError("Could not prepare voice recording for GPT Audio Mini")
        max_audio_bytes = self.settings.max_ws_recording_seconds * 32_000 + 4_096
        if len(audio) > max_audio_bytes:
            raise RuntimeError("Decoded voice recording exceeds the audio limit")
        return base64.b64encode(audio).decode("ascii")

    def create_turn(
        self,
        *,
        audio_sink: AudioSink,
        audio_input: str | None = None,
        trace_id: str | None = None,
        system_instruction: str | None = None,
    ) -> "OpenRouterAudioMiniTurn":
        return OpenRouterAudioMiniTurn(
            self,
            audio_sink=audio_sink,
            audio_input=audio_input,
            trace_id=trace_id,
            system_instruction=system_instruction,
        )


class OpenRouterAudioMiniTurn:
    def __init__(
        self,
        service: OpenRouterAudioMiniService,
        *,
        audio_sink: AudioSink,
        audio_input: str | None,
        trace_id: str | None,
        system_instruction: str | None,
    ) -> None:
        self.service = service
        self.audio_sink = audio_sink
        self.audio_input = audio_input
        self.trace_id = trace_id
        self.system_instruction = system_instruction

    async def stream_reply(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield reply text and stream raw mono PCM16 audio to the browser sink."""
        if not self.service.settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for GPT Audio Mini")
        if not messages or messages[-1].get("role") != "user":
            raise ValueError("GPT Audio Mini requires a current user turn")

        request_messages: list[dict[str, Any]] = [dict(message) for message in messages]
        if self.system_instruction:
            if request_messages and request_messages[0].get("role") == "system":
                request_messages[0]["content"] = (
                    str(request_messages[0].get("content", ""))
                    + " "
                    + self.system_instruction
                )
            else:
                request_messages.insert(0, {"role": "system", "content": self.system_instruction})
        if self.audio_input is not None:
            request_messages[-1] = {
                "role": "user",
                "content": [{
                    "type": "input_audio",
                    "input_audio": {"data": self.audio_input, "format": "wav"},
                }],
            }

        payload = {
            "model": self.service.settings.voice_audio_model,
            "messages": request_messages,
            "modalities": ["text", "audio"],
            "audio": {
                "voice": self.service.settings.voice_audio_voice,
                "format": "pcm16",
            },
            "max_tokens": self.service.settings.voice_audio_max_tokens,
            "stream": True,
        }
        text_deltas = 0
        audio_bytes_sent = 0
        encoded_pending = ""
        pcm_pending = b""
        saw_done = False

        async with provider_slot(self.service.semaphore):
            await reserve_provider_call("openrouter_chat")
            async with self.service.client.stream(
                "POST", "/chat/completions", json=payload
            ) as response:
                if response.is_error:
                    # Do not include provider response bodies in user-facing/log output;
                    # they may echo request fragments or operational metadata.
                    raise RuntimeError(
                        f"OpenRouter GPT Audio Mini returned HTTP {response.status_code}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    try:
                        item = json.loads(data)
                    except json.JSONDecodeError:
                        logger.debug("Ignoring malformed GPT Audio Mini SSE event")
                        continue
                    choices = item.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    audio = delta.get("audio") or {}
                    text_delta = delta.get("content") or audio.get("transcript") or ""
                    if text_delta:
                        text_deltas += 1
                        yield str(text_delta)
                    encoded = audio.get("data")
                    if not encoded:
                        continue
                    encoded_pending += str(encoded)
                    complete_length = len(encoded_pending) - (len(encoded_pending) % 4)
                    if complete_length:
                        complete, encoded_pending = (
                            encoded_pending[:complete_length], encoded_pending[complete_length:]
                        )
                        try:
                            pcm_pending += base64.b64decode(complete, validate=True)
                        except (binascii.Error, ValueError) as error:
                            raise RuntimeError("GPT Audio Mini returned invalid PCM encoding") from error
                        safe_length = len(pcm_pending) - (len(pcm_pending) % 2)
                        if safe_length:
                            pcm = pcm_pending[:safe_length]
                            pcm_pending = pcm_pending[safe_length:]
                            await self.audio_sink(pcm)
                            audio_bytes_sent += len(pcm)

        if encoded_pending:
            try:
                pcm_pending += base64.b64decode(encoded_pending, validate=True)
            except (binascii.Error, ValueError) as error:
                raise RuntimeError("GPT Audio Mini ended with invalid PCM encoding") from error
        if len(pcm_pending) % 2:
            raise RuntimeError("GPT Audio Mini returned an incomplete PCM sample")
        if pcm_pending:
            await self.audio_sink(pcm_pending)
            audio_bytes_sent += len(pcm_pending)
        if not saw_done:
            logger.warning("GPT Audio Mini stream ended without an SSE done marker")
        if not text_deltas:
            raise RuntimeError("GPT Audio Mini returned no reply text")
        if not audio_bytes_sent:
            raise RuntimeError("GPT Audio Mini returned no playable audio")
        logger.info(
            "GPT Audio Mini stream complete model=%s audio_bytes=%d trace_id=%s",
            self.service.settings.voice_audio_model,
            audio_bytes_sent,
            self.trace_id or "untracked",
        )
