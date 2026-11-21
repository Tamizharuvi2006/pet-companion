"""OpenRouter audio understanding plus text reply, not realtime transcription."""
import asyncio
import base64
from collections.abc import AsyncIterator
from pathlib import Path

from openai import AsyncOpenAI
from app.core.config import Settings

from app.services.provider_budget import reserve_provider_call
from app.services.request_limits import provider_slot


class AudioReplyService:
    def __init__(self, settings: Settings, semaphore: asyncio.Semaphore | None = None):
        self.settings = settings
        self.semaphore = semaphore
        self.client = AsyncOpenAI(api_key=settings.openrouter_api_key,
                                 base_url='https://openrouter.ai/api/v1',
                                 max_retries=0, timeout=settings.openrouter_timeout_seconds)

    async def close(self) -> None:
        await self.client.close()

    async def prepare(self, path: Path) -> 'AudioReplyTurn':
        # Use a finalized WAV; MediaRecorder WebM segments are not independent
        # decodable utterances. Avoid subprocess pipes containing credentials.
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-v', 'error', '-i', str(path),
            '-t', str(self.settings.max_ws_recording_seconds + 1), '-ar', '16000', '-ac', '1',
            '-c:a', 'pcm_s16le',
            '-f', 'wav', 'pipe:1', stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        try:
            audio, _ = await asyncio.wait_for(process.communicate(), 10)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode != 0 or not audio:
            raise RuntimeError('Could not prepare voice recording')
        if len(audio) > self.settings.max_ws_recording_seconds * 32000 + 4096:
            raise RuntimeError('Decoded voice recording exceeds the audio limit')
        return AudioReplyTurn(self, base64.b64encode(audio).decode('ascii'))


class AudioReplyTurn:
    def __init__(self, service: AudioReplyService, encoded: str) -> None:
        self.service = service
        self.encoded = encoded

    async def stream_reply(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        # Only the current placeholder is replaced. Earlier voice turns remain
        # explicitly marked, rather than inventing transcripts for memory.
        request_messages = [dict(message) for message in messages]
        if not request_messages or request_messages[-1].get('role') != 'user':
            raise ValueError('Audio reply requires a current user turn')
        request_messages[-1] = {'role': 'user', 'content': [
            {'type': 'input_audio', 'input_audio': {'data': self.encoded, 'format': 'wav'}}]}
        async with provider_slot(self.service.semaphore):
            await reserve_provider_call('openrouter_chat')
            stream = await self.service.client.chat.completions.create(
                model=self.service.settings.voice_audio_model,
                messages=request_messages, max_tokens=self.service.settings.max_tokens,
                stream=True)
            try:
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            finally:
                await stream.close()
