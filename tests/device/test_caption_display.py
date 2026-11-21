import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.device.protocol import AUDIO_TYPE_SPEAKER, PCM_FRAME_BYTES, pack_audio_frame
from app.device.registry import DeviceRegistry
from app.device.websocket import router as device_router
from app.memory.short_term import ShortTermMemory
from app.services.context_service import ContextService

DEVICE_ID = "caption-test-device"
DEVICE_TOKEN = "caption-test-token-long-enough-for-schema"


def test_device_audio_mini_streams_reply_text_and_persists_caption_toggle(
    tmp_path, monkeypatch
) -> None:
    from app.device import websocket as device_websocket

    audio_chunks: list[bytes] = []
    turn_instructions: list[str | None] = []

    class FakeWhisper:
        async def transcribe(self, _path):
            return "Turn captions off."

    class FakeTurn:
        def __init__(self, audio_sink, system_instruction):
            self.audio_sink = audio_sink
            turn_instructions.append(system_instruction)

        async def stream_reply(self, messages):
            assert messages[-1] == {"role": "user", "content": "Turn captions off."}
            yield "Sure, captions are off."
            await self.audio_sink(b"\x01\x00" * 1920)

    class FakeAudioMini:
        def create_turn(self, *, audio_sink, **kwargs):
            return FakeTurn(audio_sink, kwargs.get("system_instruction"))

    async def fake_audio_bridge(websocket, pcm_chunks, *, turn_id, chunk_id,
                                trace_id, max_frame_bytes, send_lock):
        sequence = 0
        async for chunk in pcm_chunks:
            audio_chunks.append(chunk)
            async with send_lock:
                if sequence == 0:
                    await websocket.send_json({
                        "type": "tts_chunk_start", "version": 1,
                        "turn_id": turn_id, "chunk_id": chunk_id,
                        "trace_id": trace_id,
                    })
                frame_size = min(PCM_FRAME_BYTES, max_frame_bytes)
                for offset in range(0, len(chunk), frame_size):
                    payload = chunk[offset:offset + frame_size]
                    payload = payload[:len(payload) - len(payload) % 2]
                    if payload:
                        await websocket.send_bytes(pack_audio_frame(
                            AUDIO_TYPE_SPEAKER, turn_id, sequence, payload
                        ))
                        sequence += 1
        async with send_lock:
            await websocket.send_json({
                "type": "tts_chunk_end", "version": 1,
                "turn_id": turn_id, "chunk_id": chunk_id,
                "trace_id": trace_id, "frame_count": sequence,
            })
        return sum(map(len, audio_chunks))

    monkeypatch.setattr(
        device_websocket, "stream_pcm24_chunks_as_device_audio", fake_audio_bridge
    )
    test_app = FastAPI()
    settings = Settings(
        device_auth_tokens={DEVICE_ID: DEVICE_TOKEN},
        storage_dir=tmp_path,
        voice_engine_default="gpt_audio_mini",
    )
    registry = DeviceRegistry()
    test_app.state.settings = settings
    test_app.state.device_registry = registry
    test_app.state.whisper = FakeWhisper()
    test_app.state.openrouter_audio_mini = FakeAudioMini()
    test_app.state.memory = ShortTermMemory(settings.max_history_messages)
    test_app.state.context = ContextService()
    test_app.state.tts = object()
    test_app.include_router(device_router)

    pcm = b"\x20\x00" * 640
    with TestClient(test_app) as client:
        with client.websocket_connect("/ws/device") as websocket:
            websocket.send_json({
                "type": "hello", "version": 1,
                "device_id": DEVICE_ID, "token": DEVICE_TOKEN,
                "capabilities": {
                    "caption_overlay_v1": True,
                    "display_captions_enabled": True,
                },
            })
            assert websocket.receive_json()["type"] == "device_ready"
            websocket.send_json({
                "type": "recording_start", "version": 1, "turn_id": 1,
                "sample_rate_hz": 16000, "channels": 1,
                "bits_per_sample": 16, "codec": "pcm_s16le",
            })
            websocket.send_bytes(pack_audio_frame(1, 1, 0, pcm))
            websocket.send_json({"type": "recording_end", "version": 1, "turn_id": 1})

            received: list[dict[str, object]] = []
            binary_frames: list[bytes] = []
            while True:
                frame = websocket.receive()
                if frame.get("bytes"):
                    binary_frames.append(frame["bytes"])
                    continue
                if frame.get("text"):
                    event = json.loads(frame["text"])
                    received.append(event)
                    if event["type"] == "turn_complete":
                        break

            kinds = [event["type"] for event in received]
            assert kinds.index("transcript") < kinds.index("display_settings")
            assert kinds.index("display_settings") < kinds.index("reply_delta")
            assert kinds.index("reply_delta") < kinds.index("tts_chunk_start")
            settings_event = next(event for event in received if event["type"] == "display_settings")
            assert settings_event["captions_enabled"] is False
            assert "setting" in (turn_instructions[0] or "").lower()
            assert b"".join(audio_chunks) == b"\x01\x00" * 1920
            assert binary_frames

            websocket.send_json({
                "type": "display_settings_ack", "version": 1,
                "captions_enabled": False, "persisted": True,
            })
            websocket.send_json({"type": "ping", "version": 1})
            assert websocket.receive_json()["type"] == "pong"
            status = asyncio.run(registry.snapshot(DEVICE_ID))[0]
            assert status["display_captions_enabled"] is False
            assert status["display_captions_persisted"] is True
