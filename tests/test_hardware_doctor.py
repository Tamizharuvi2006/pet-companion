"""Hardware Doctor reports evidence levels without leaking private device data."""

from app.device.doctor import build_hardware_doctor


def test_empty_device_stays_pending_and_reports_disabled_features_honestly():
    report = build_hardware_doctor(None, "bella")
    assert report["overall"] == "PENDING"
    assert report["checks"]["connection"]["status"] == "PENDING"
    assert report["checks"]["display_bus"]["status"] == "UNSUPPORTED"
    assert report["checks"]["display_visible"]["status"] == "PENDING"
    assert report["checks"]["speaker_audible"]["status"] == "PENDING"
    assert report["checks"]["camera"]["status"] == "UNSUPPORTED"
    assert report["checks"]["last_error"]["status"] == "PASS"


def test_authenticated_report_uses_sensor_evidence_and_sanitizes_private_fields():
    record = {
        "device_id": "bella",
        "connected": True,
        "last_heartbeat": "2026-11-15T00:00:00+00:00",
        "firmware_version": "0.1.0",
        "state": "IDLE",
        "capabilities": {"tft_profile": "st7789-240x240", "camera": "separate_board_optional"},
        "sensors": {
            "display_initialized": True,
            "display_frames": 12,
            "touch_seen_mask": 5,
            "distance_initialized": True,
            "distance_valid": True,
            "distance_valid_samples": 3,
            "distance_mm": 450,
            "i2s_input_ready": True,
            "mic_frames": 5,
            "mic_last_rms": 132,
            "i2s_output_ready": True,
            "audio_dropped_frames": 0,
            "servo_enabled": False,
            "servo2_gpio12_enabled": False,
            "servo2_gpio12_strap_gate_open": False,
            "transcript": "PRIVATE SPEECH",
            "device_token": "PRIVATE TOKEN",
        },
        "playback_status": "drained",
        "playback_basis": "dma_ring_fence",
        "last_error": "PRIVATE RAW ERROR",
    }
    report = build_hardware_doctor(record, "bella")
    assert report["checks"]["display_bus"]["status"] == "PASS"
    assert report["checks"]["display_visible"]["status"] == "PENDING"
    assert report["checks"]["touch_1"]["status"] == "PASS"
    assert report["checks"]["touch_2"]["status"] == "PENDING"
    assert report["checks"]["touch_3"]["status"] == "PASS"
    assert report["checks"]["microphone"]["status"] == "PASS"
    assert report["checks"]["speaker_i2s"]["status"] == "PASS"
    assert report["checks"]["speaker_audible"]["status"] == "PENDING"
    assert report["checks"]["servo_safety"]["status"] == "PASS"
    assert report["checks"]["last_error"]["status"] == "FAIL"
    assert report["sanitized_device_data"]["last_error_category"] == "unspecified_error"
    exported = str(report)
    assert "PRIVATE SPEECH" not in exported
    assert "PRIVATE TOKEN" not in exported
    assert "PRIVATE RAW ERROR" not in exported


def test_camera_capture_is_explicit_bounded_and_validates_jpeg(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.face import router
    from app.core.config import Settings
    from app.device.registry import DeviceRegistry
    from app.services.request_limits import SlidingWindowRateLimiter

    jpeg = b"\xff\xd8\xff" + b"test-frame"
    upstream = {"content_type": "image/jpeg", "body": jpeg, "status": 200}

    class Response:
        def __init__(self, content_type, body, status):
            self.headers = {"content-type": content_type}
            self.body = body
            self.status = status

        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        def raise_for_status(self):
            if self.status >= 400: raise httpx.HTTPStatusError("upstream failure", request=None, response=None)
        async def aiter_bytes(self, _size):
            yield self.body

    class Client:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        def stream(self, *_args, **_kwargs):
            return Response(upstream["content_type"], upstream["body"], upstream["status"])

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    test_app = FastAPI()
    test_app.state.settings = Settings(
        camera_enabled=True,
        camera_base_url="http://camera.local",
        camera_token="offline-camera-token",
        device_auth_tokens={"bella": "offline-device-token-123456789"},
    )
    test_app.state.device_registry = DeviceRegistry()
    test_app.state.rate_limiter = SlidingWindowRateLimiter()
    test_app.include_router(router)
    with TestClient(test_app) as client:
        # Nothing is captured on page load: the only call is this explicit POST.
        response = client.post("/api/face/bella/camera/capture")
        assert response.status_code == 200 and response.content == jpeg
        upstream["body"] = b"not-jpeg"
        invalid = client.post("/api/face/bella/camera/capture")
        assert invalid.status_code == 502
        upstream["body"] = b"\xff\xd8\xff" + b"x" * 1_050_000
        oversized = client.post("/api/face/bella/camera/capture")
        assert oversized.status_code == 413
