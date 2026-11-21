import asyncio
import base64
import threading
import pytest

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.services.openrouter_stt_service import OpenRouterSTTService


@pytest.mark.parametrize('cancel_event', ['audio_chunk', 'cancel_recording'])
def test_new_capture_cancels_old_provider_before_recording_finishes(monkeypatch, tmp_path, cancel_event):
    started, cancelled = threading.Event(), threading.Event()
    settings = Settings(environment="development", storage_dir=tmp_path,
                        openrouter_api_key="offline-test", whisper_preload_enabled=False,
                        whisper_interim_enabled=False, voice_engine_default="current")
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    async def blocked_stt(self, path, **options):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(OpenRouterSTTService, "transcribe", blocked_stt)
    audio = base64.b64encode(b"synthetic audio").decode()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "audio_chunk", "data": audio, "capture_id": "old"})
            ws.send_json({"type": "stop_recording", "capture_id": "old"})
            assert started.wait(2), "old turn never reached provider"
            ws.send_json({"type": cancel_event, "data": audio, "capture_id": "new"})
            assert cancelled.wait(2), "new capture was blocked behind old provider"
        assert app.state.voice_turn_gate._active == 0
