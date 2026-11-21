import asyncio
import base64
import json

import httpx
import pytest

from app.core.config import Settings
from app.services.openrouter_audio_mini_service import OpenRouterAudioMiniService


def _sse(data: dict[str, object]) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode()


def test_audio_mini_streams_text_and_decodable_pcm_incrementally():
    async def run() -> None:
        pcm = b"\x01\x00\x02\x00"
        encoded = base64.b64encode(pcm).decode("ascii")
        events = [
            {"choices": [{"delta": {"audio": {"transcript": "Hello", "data": encoded[:4]}}}]},
            {"choices": [{"delta": {"audio": {"transcript": " there.", "data": encoded[4:]}}}]},
        ]
        body = b"".join(_sse(item) for item in events) + b"data: [DONE]\n\n"
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            captured["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

        settings = Settings(openrouter_api_key="test-key", voice_audio_model="openai/gpt-audio-mini")
        service = OpenRouterAudioMiniService(settings)
        await service.close()
        service.client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer test-key"},
        )
        received: list[bytes] = []

        async def receive_audio(chunk: bytes) -> None:
            received.append(chunk)

        try:
            turn = service.create_turn(audio_sink=receive_audio)
            parts = [part async for part in turn.stream_reply([
                {"role": "system", "content": "Bella"},
                {"role": "user", "content": "Say hello."},
            ])]
            request = captured["json"]
            assert parts == ["Hello", " there."]
            assert b"".join(received) == pcm
            assert request["model"] == "openai/gpt-audio-mini"
            assert request["modalities"] == ["text", "audio"]
            assert request["audio"] == {"voice": "shimmer", "format": "pcm16"}
            assert request["max_tokens"] == 512
            assert request["stream"] is True
            assert captured["authorization"] == "Bearer test-key"
            assert request["messages"][-1]["content"] == "Say hello."
        finally:
            await service.close()

    asyncio.run(run())


def test_audio_mini_replaces_only_current_user_turn_with_audio_input():
    async def run() -> None:
        events = [{"choices": [{"delta": {"audio": {
            "transcript": "I heard you.", "data": base64.b64encode(b"\x00\x00").decode(),
        }}}]}]
        body = b"".join(_sse(item) for item in events) + b"data: [DONE]\n\n"
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, content=body)

        service = OpenRouterAudioMiniService(Settings(openrouter_api_key="test-key"))
        await service.close()
        service.client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler)
        )
        original = [
            {"role": "system", "content": "Bella"},
            {"role": "user", "content": "Earlier text"},
            {"role": "assistant", "content": "Earlier reply"},
            {"role": "user", "content": "[Voice message]"},
        ]
        received: list[bytes] = []
        try:
            turn = service.create_turn(
                audio_sink=lambda chunk: _append_async(received, chunk), audio_input="encoded-wav"
            )
            parts = [part async for part in turn.stream_reply(original)]
            request_messages = captured["json"]["messages"]
            assert parts == ["I heard you."]
            assert request_messages[:-1] == original[:-1]
            assert request_messages[-1] == {
                "role": "user",
                "content": [{"type": "input_audio", "input_audio": {
                    "data": "encoded-wav", "format": "wav",
                }}],
            }
            assert original[-1]["content"] == "[Voice message]"
            assert b"".join(received) == b"\x00\x00"
        finally:
            await service.close()

    asyncio.run(run())


async def _append_async(target: list[bytes], chunk: bytes) -> None:
    target.append(chunk)


def test_audio_mini_rejects_invalid_base64_audio():
    async def run() -> None:
        body = _sse({"choices": [{"delta": {"audio": {
            "transcript": "Hello.", "data": "!!!!",
        }}}]}) + b"data: [DONE]\n\n"

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body)

        service = OpenRouterAudioMiniService(Settings(openrouter_api_key="test-key"))
        await service.close()
        service.client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler)
        )
        try:
            turn = service.create_turn(audio_sink=lambda _chunk: asyncio.sleep(0))
            with pytest.raises(RuntimeError, match="invalid PCM encoding"):
                _ = [part async for part in turn.stream_reply([{"role": "user", "content": "Hi"}])]
        finally:
            await service.close()

    asyncio.run(run())
