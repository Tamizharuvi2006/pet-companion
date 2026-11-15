import base64
import json

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.services.ai_service import AIService
from app.services.openrouter_stt_service import OpenRouterSTTService
from app.services.openrouter_tts_service import OpenRouterTTSService
from app.services.tts_service import TTSAudioChunk


def test_voice_diagnostic_labels_first_phrase_and_never_queues_second(
    monkeypatch, tmp_path
) -> None:
    settings = Settings(
        environment="development",
        openrouter_api_key="offline-test-only",
        voice_diagnostic_mode=True,
        whisper_interim_enabled=False,
        tts_race_enabled=False,
        storage_dir=tmp_path,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    tts_texts: list[str] = []
    stt_calls: list[bool] = []
    streamed_chat_calls: list[bool] = []
    http_chat_calls: list[bool] = []

    async def fake_transcribe(_self, _path, *, interim: bool = False) -> str:
        assert not interim
        stt_calls.append(interim)
        return "test transcript"

    async def fake_stream_reply(_self, _messages):
        streamed_chat_calls.append(True)
        yield "Hello there. "
        yield "The remaining response is still shown as text."

    async def fake_reply(_self, _messages):
        http_chat_calls.append(True)
        return "offline response"

    async def fake_synthesize(_self, text: str, **_options: object) -> str:
        tts_texts.append(text)
        return "/audio/offline-test.mp3"

    monkeypatch.setattr(OpenRouterSTTService, "transcribe", fake_transcribe)
    monkeypatch.setattr(AIService, "stream_reply", fake_stream_reply)
    monkeypatch.setattr(AIService, "reply", fake_reply)
    monkeypatch.setattr(OpenRouterTTSService, "synthesize", fake_synthesize)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "client_capabilities", "streaming_mp3": False})
            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "data": base64.b64encode(b"offline audio fixture").decode("ascii"),
                    "capture_id": "offline-capture",
                }
            )
            websocket.send_json(
                {"type": "stop_recording", "capture_id": "offline-capture"}
            )
            events = []
            while True:
                event = websocket.receive_json()
                events.append(event)
                if event.get("type") == "status" and event.get("text") == "Ready":
                    break

            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "data": base64.b64encode(b"second offline attempt").decode("ascii"),
                    "capture_id": "second-offline-capture",
                }
            )
            rejected = websocket.receive_json()
            assert rejected["type"] == "error"
            assert rejected["code"] == "diagnostic_session_consumed"

        response = client.post("/chat", json={"text": "must be refused"})
        assert response.status_code == 409
        assert response.json()["code"] == "diagnostic_session_consumed"

    assert tts_texts == ["Hello there."]
    assert len(stt_calls) == len(streamed_chat_calls) == 1
    assert http_chat_calls == []
    assert any(
        event.get("type") == "diagnostic_audio_mode"
        and event.get("text")
        == "FIRST-PHRASE-ONLY AUDIO — the rest of Bella's reply is text only."
        for event in events
    )
    assert sum(event.get("type") == "audio" for event in events) == 1
    assert "The remaining response is still shown as text." in "".join(
        event.get("text", "") for event in events if event.get("type") == "reply_delta"
    )


def test_bounded_full_voice_mode_sends_complete_reply_and_consumes_shared_latch(
    monkeypatch, tmp_path
) -> None:
    settings = Settings(
        environment="development",
        openrouter_api_key="offline-test-only",
        bounded_full_voice_test=True,
        whisper_interim_enabled=False,
        tts_race_enabled=False,
        storage_dir=tmp_path,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    async def fake_load(_self) -> None:
        return None

    async def fake_transcribe(_self, _path, *, interim: bool = False) -> str:
        assert not interim
        return "offline transcript"

    async def fake_stream_reply(_self, _messages):
        yield "Hello there, sweet friend!"
        yield " This second phrase has fifteen nice words for a calm and natural speech segment today."
        yield " A third phrase keeps Bella speaking smoothly while the remaining reply arrives from GPT."
        yield " A fourth phrase must join the final segment without losing words or changing their order."

    tts_texts: list[str] = []

    async def fake_stream_audio(_self, text: str, **_options):
        tts_texts.append(text)
        yield TTSAudioChunk(provider="offline-only", data=b"synthetic-mp3")

    monkeypatch.setattr("app.services.whisper_service.WhisperService.load", fake_load)
    monkeypatch.setattr(OpenRouterSTTService, "transcribe", fake_transcribe)
    monkeypatch.setattr(AIService, "stream_reply", fake_stream_reply)
    monkeypatch.setattr(OpenRouterTTSService, "stream_audio", fake_stream_audio)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "client_capabilities", "streaming_mp3": True})
            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "data": base64.b64encode(b"offline audio fixture").decode("ascii"),
                    "capture_id": "full-voice-capture",
                }
            )
            websocket.send_json(
                {"type": "stop_recording", "capture_id": "full-voice-capture"}
            )
            events: list[dict[str, object]] = []
            binary_chunks = 0
            while True:
                message = websocket.receive()
                if message.get("bytes") is not None:
                    binary_chunks += 1
                    continue
                event = json.loads(message["text"])
                events.append(event)
                if event.get("type") == "status" and event.get("text") == "Ready":
                    break

            banner = next(event for event in events if event.get("type") == "diagnostic_audio_mode")
            assert "BOUNDED FULL-REPLY AUDIO" in banner["text"]
            coverage = next(event for event in events if event.get("type") == "speech_coverage")
            assert coverage["complete"] is True
            assert "delivery, not audible playback" in coverage["text"]
            assert sum(event.get("type") == "tts_stream_start" for event in events) == 3
            assert binary_chunks == 3
            assert len(tts_texts) == 3
            streamed_text = "".join(
                str(event.get("text", ""))
                for event in events
                if event.get("type") == "reply_delta"
            )
            assert "fourth phrase" in streamed_text

            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "data": base64.b64encode(b"second offline attempt").decode("ascii"),
                    "capture_id": "second-full-voice-capture",
                }
            )
            rejected = websocket.receive_json()
            assert rejected["type"] == "error"
            assert rejected["code"] == "diagnostic_session_consumed"

        rejected_http = client.post("/chat", json={"text": "must not reach provider"})
        assert rejected_http.status_code == 409
        assert rejected_http.json()["code"] == "diagnostic_session_consumed"
