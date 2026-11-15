import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.services.ai_service import AIService
from app.services.diagnostic_session import (
    DiagnosticSessionConsumedError,
    DiagnosticSessionLatch,
)


def test_diagnostic_session_has_one_atomic_slot_across_http_and_websocket() -> None:
    async def run() -> None:
        latch = DiagnosticSessionLatch(enabled=True)
        sources = ["http:POST:/talk", *("websocket:audio" for _ in range(31))]

        async def try_claim(source: str) -> str:
            try:
                await latch.claim(source)
                return "accepted"
            except DiagnosticSessionConsumedError:
                return "rejected"

        outcomes = await asyncio.gather(*(try_claim(source) for source in sources))
        assert outcomes.count("accepted") == 1
        assert outcomes.count("rejected") == len(sources) - 1
        snapshot = await latch.snapshot()
        assert snapshot["claimed"] is True
        assert snapshot["accepted_source"] in sources
        assert snapshot["rejected_attempts"] == len(sources) - 1

    asyncio.run(run())


def test_cancellation_after_claim_does_not_refund_diagnostic_session() -> None:
    async def run() -> None:
        latch = DiagnosticSessionLatch(enabled=True)

        async def cancelled_request() -> None:
            await latch.claim("websocket:audio")
            await asyncio.sleep(10)

        request = asyncio.create_task(cancelled_request())
        await asyncio.sleep(0)
        assert (await latch.snapshot())["claimed"] is True
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        with pytest.raises(DiagnosticSessionConsumedError):
            await latch.claim("http:POST:/talk")

    asyncio.run(run())


def test_http_paid_routes_share_one_shot_diagnostic_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path
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
    chat_calls: list[bool] = []

    async def fake_reply(_self, _messages):
        chat_calls.append(True)
        return "offline only"

    monkeypatch.setattr(AIService, "reply", fake_reply)

    with TestClient(app) as client:
        first = client.post("/chat", json={"text": "offline test"})
        assert first.status_code == 200
        assert first.json()["reply"] == "offline only"

        second = client.post("/tts", json={"text": "must not reach TTS"})
        assert second.status_code == 409
        assert second.json()["code"] == "diagnostic_session_consumed"

    assert chat_calls == [True]


def test_normal_mode_diagnostic_latch_does_not_consume() -> None:
    async def run() -> None:
        latch = DiagnosticSessionLatch(enabled=False)
        await asyncio.gather(latch.claim("http:POST:/chat"), latch.claim("websocket:audio"))
        snapshot = await latch.snapshot()
        assert snapshot["enabled"] is False
        assert snapshot["claimed"] is False

    asyncio.run(run())
