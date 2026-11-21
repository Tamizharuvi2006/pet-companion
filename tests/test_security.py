import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings, get_settings
from app.main import app
from app.services.browser_security import issue_session, origin_is_allowed, verify_session
from app.services.request_limits import CapacityGate, SlidingWindowRateLimiter


def _public_settings() -> Settings:
    return Settings(
        environment="production",
        browser_access_password="a-long-private-test-password",
        browser_session_secret="x" * 48,
        browser_allowed_origins=("https://bella.example",),
    )


def test_public_mode_fails_closed_without_authentication_configuration() -> None:
    settings = Settings(environment="production")
    with pytest.raises(RuntimeError, match="BELLA_ACCESS_PASSWORD"):
        settings.validate_public_security()


def test_public_mode_rejects_non_https_or_non_origin_allowlist_entries() -> None:
    for origin in ("http://bella.example", "https://bella.example/path", "https://user@bella.example"):
        with pytest.raises(RuntimeError, match="exact HTTPS origins"):
            _public_settings().model_copy(update={"browser_allowed_origins": (origin,)}).validate_public_security()


def test_public_camera_requires_https_and_private_development_camera_can_use_http() -> None:
    http_camera = {
        "camera_enabled": True,
        "camera_base_url": "http://camera.example",
        "camera_token": "camera-token-123456",
    }
    with pytest.raises(RuntimeError, match="public mode requires HTTPS"):
        _public_settings().model_copy(update=http_camera).validate_public_security()

    secure = _public_settings().model_copy(
        update={**http_camera, "camera_base_url": "https://camera.example"}
    )
    secure.validate_public_security()
    assert secure.camera_transport_ready

    local = Settings(**{**http_camera, "environment": "development"})
    local.camera_base_url = "http://camera.local"
    assert local.camera_transport_ready
    assert not Settings(**{**http_camera, "environment": "development"}).camera_transport_ready


def test_signed_session_token_detects_tampering_and_expiry() -> None:
    settings = _public_settings()
    token, session_id, _ = issue_session(settings)
    assert verify_session(settings, token) == session_id
    assert verify_session(settings, token + "x") is None
    assert verify_session(settings.model_copy(update={"browser_session_secret": "y" * 48}), token) is None


def test_origin_allowlist_is_exact_and_development_checks_host() -> None:
    settings = _public_settings()
    assert origin_is_allowed("https://bella.example", "other.example", settings)
    assert not origin_is_allowed("https://evil.example", "bella.example", settings)
    assert origin_is_allowed("http://localhost:8000", "localhost:8000", Settings())
    assert not origin_is_allowed("http://evil.example", "localhost:8000", Settings())


def test_browser_paid_routes_require_login_and_login_sets_hardened_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("BELLA_ACCESS_PASSWORD", "a-long-private-test-password")
    monkeypatch.setenv("BELLA_SESSION_SECRET", "x" * 48)
    monkeypatch.setenv("BELLA_ALLOWED_ORIGINS", "https://bella.example")
    get_settings.cache_clear()

    with TestClient(app, base_url="https://bella.example") as client:
        assert client.get("/auth/session").json() == {"required": True, "authenticated": False}
        assert client.get("/client-config").status_code == 401
        assert client.post(
            "/tts",
            json={"text": "hello"},
            headers={"Origin": "https://bella.example"},
        ).status_code == 401
        for path, kwargs in (
            ("/chat", {"json": {"text": "hello"}}),
            ("/stt", {}),
            ("/talk", {}),
        ):
            assert client.post(
                path,
                headers={"Origin": "https://bella.example"},
                **kwargs,
            ).status_code == 401
        assert client.get("/audio/missing.mp3").status_code == 401
        assert client.post(
            "/auth/login",
            json={"password": "wrong"},
            headers={"Origin": "https://evil.example"},
        ).status_code == 403
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/chat", headers={"Origin": "https://bella.example"}
            ) as websocket:
                websocket.receive_json()

        response = client.post(
            "/auth/login",
            json={"password": "a-long-private-test-password"},
            headers={"Origin": "https://bella.example"},
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
        assert client.get("/auth/session").json() == {"required": True, "authenticated": True}
        assert client.get("/client-config").json() == {"pet_voice_synthesis_enabled": True}
        assert client.get("/metrics").status_code == 200
        with client.websocket_connect(
            "/ws/chat",
            headers={
                "Origin": "https://bella.example",
                "Cookie": response.headers["set-cookie"].split(";", 1)[0],
            },
        ) as websocket:
            websocket.send_json({"type": "client_capabilities", "streaming_mp3": True})

    get_settings.cache_clear()


def test_websocket_rejects_bad_base64_and_oversized_audio_without_provider_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_WS_AUDIO_FRAME_BYTES", "1280")
    get_settings.cache_clear()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "audio_chunk", "data": "!bad-base64!", "capture_id": "bad"})
            malformed = websocket.receive_json()
            assert malformed["code"] == "invalid_audio"
            websocket.send_json({"type": "stop_recording", "capture_id": "bad"})

            oversized = "A" * 1712
            websocket.send_json({"type": "audio_chunk", "data": oversized, "capture_id": "large"})
            rejected = websocket.receive_json()
            assert rejected["code"] == "frame_too_large"
            websocket.send_json({"type": "stop_recording", "capture_id": "large"})
    get_settings.cache_clear()


def test_websocket_bounds_cumulative_recording_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.setenv("MAX_WS_AUDIO_FRAME_BYTES", "65536")
    monkeypatch.setenv("MAX_WS_RECORDING_BYTES", "65536")
    get_settings.cache_clear()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json(
                {"type": "audio_chunk", "data": base64.b64encode(b"a" * 40_000).decode(), "capture_id": "bounded"}
            )
            websocket.send_json(
                {"type": "audio_chunk", "data": base64.b64encode(b"b" * 26_000).decode(), "capture_id": "bounded"}
            )
            rejected = websocket.receive_json()
            assert rejected["code"] == "recording_too_large"
            websocket.send_json({"type": "stop_recording", "capture_id": "bounded"})
    get_settings.cache_clear()


def test_websocket_uses_server_elapsed_time_not_client_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    import app.api.websocket as websocket_api

    monkeypatch.setenv("MAX_WS_RECORDING_SECONDS", "1")
    get_settings.cache_clear()
    clock = [100.0]
    monkeypatch.setattr(websocket_api, "perf_counter", lambda: clock[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "data": base64.b64encode(b"first frame").decode(),
                    "duration_ms": 10_000,
                    "capture_id": "timed",
                }
            )
            clock[0] += 2.0
            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "data": base64.b64encode(b"second frame").decode(),
                    "duration_ms": 1,
                    "capture_id": "timed",
                }
            )
            rejected = websocket.receive_json()
            assert rejected["code"] == "recording_too_long"
            websocket.send_json({"type": "stop_recording", "capture_id": "timed"})
    get_settings.cache_clear()


def test_rate_limiter_and_capacity_gate_are_bounded() -> None:
    async def run() -> None:
        limiter = SlidingWindowRateLimiter(max_keys=2)
        assert await limiter.allow("one", 1)
        assert not await limiter.allow("one", 1)
        assert await limiter.allow("two", 1)
        assert await limiter.allow("three", 1)
        assert len(limiter._buckets) == 2

        gate = CapacityGate(1)
        assert await gate.acquire()
        assert not await gate.acquire()
        await gate.release()
        assert await gate.acquire()
        await gate.release()

    asyncio.run(run())
