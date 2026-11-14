from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.device.http import router as device_http_router
from app.device.pinmap import BOOT_STRAP_WARNINGS, PIN_MAP, validate_pin_map
from app.device.protocol import (
    AUDIO_TYPE_MICROPHONE,
    PCM_FRAME_BYTES,
    PROTOCOL_VERSION,
    pack_audio_frame,
    parse_audio_frame,
    parse_control_message,
)
from app.device.registry import DeviceRegistry
from app.device.security import verify_device_token
from app.device.websocket import router as device_websocket_router

DEVICE_ID = "unit-test-device"
DEVICE_TOKEN = "test-device-token-long-enough-for-schema"


def _app(tmp_path) -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        device_auth_tokens={DEVICE_ID: DEVICE_TOKEN}, storage_dir=tmp_path
    )
    app.state.device_registry = DeviceRegistry()
    app.include_router(device_websocket_router)
    app.include_router(device_http_router)
    return app


def test_protocol_pcm_frame_round_trip() -> None:
    payload = bytes(range(256)) * 5
    frame_bytes = pack_audio_frame(AUDIO_TYPE_MICROPHONE, 7, 3, payload)
    frame = parse_audio_frame(frame_bytes, max_payload_bytes=PCM_FRAME_BYTES)

    assert frame.message_type == AUDIO_TYPE_MICROPHONE
    assert frame.version == PROTOCOL_VERSION
    assert frame.turn_id == 7
    assert frame.sequence == 3
    assert frame.payload == payload


def test_protocol_rejects_oversized_frame() -> None:
    oversized = bytes(PCM_FRAME_BYTES + 2)
    try:
        pack_audio_frame(AUDIO_TYPE_MICROPHONE, 1, 0, oversized)
    except ValueError as error:
        assert "40 ms" in str(error)
    else:
        raise AssertionError("oversized audio frame was accepted")


def test_device_token_is_per_device_and_exact() -> None:
    settings = Settings(device_auth_tokens={DEVICE_ID: DEVICE_TOKEN})
    assert verify_device_token(settings, DEVICE_ID, DEVICE_TOKEN)
    assert not verify_device_token(settings, DEVICE_ID, DEVICE_TOKEN + "x")
    assert not verify_device_token(settings, "other-device", DEVICE_TOKEN)


def test_pin_map_has_only_intentional_sharing() -> None:
    assert validate_pin_map() == []
    assert {assignment.signal for assignment in PIN_MAP[26]} == {"bclk"}
    assert all(assignment.shared_bus == "i2s_full_duplex" for assignment in PIN_MAP[26])
    assert {assignment.signal for assignment in PIN_MAP[12]} == {"signal"}
    assert PIN_MAP[12][0].owner == "servo2"
    assert PIN_MAP[21][0].owner == "existing_hardware"
    assert PIN_MAP[21][0].signal == "reserved"
    assert 12 in BOOT_STRAP_WARNINGS
    assert BOOT_STRAP_WARNINGS.keys() <= PIN_MAP.keys()


def test_reserved_gpio_cannot_be_reassigned() -> None:
    from app.device.pinmap import PinUse

    pin_map = dict(PIN_MAP)
    pin_map[21] = (*PIN_MAP[21], PinUse("servo2", "signal"))
    assert "GPIO21 is assigned more than once" in validate_pin_map(pin_map)[0]


def test_websocket_requires_device_token_and_accepts_silence_guard(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/device") as websocket:
            websocket.send_json(
                {
                    "type": "hello",
                    "version": PROTOCOL_VERSION,
                    "device_id": DEVICE_ID,
                    "token": DEVICE_TOKEN,
                    "firmware_version": "test",
                }
            )
            assert websocket.receive_json()["type"] == "device_ready"
            websocket.send_json(
                {
                    "type": "recording_start",
                        "version": PROTOCOL_VERSION,
                    "turn_id": 1,
                    "sample_rate_hz": 16000,
                    "channels": 1,
                    "bits_per_sample": 16,
                    "codec": "pcm_s16le",
                }
            )
            websocket.send_bytes(pack_audio_frame(AUDIO_TYPE_MICROPHONE, 1, 0, bytes(PCM_FRAME_BYTES)))
            websocket.send_json({"type": "recording_end", "version": PROTOCOL_VERSION, "turn_id": 1})
            messages = [websocket.receive_json(), websocket.receive_json()]
            assert [message["type"] for message in messages] == ["error", "turn_complete"]
            assert messages[0]["code"] == "silent_audio"


def test_websocket_rejects_replayed_turn_id(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/device") as websocket:
            websocket.send_json(
                {
                    "type": "hello",
                    "version": PROTOCOL_VERSION,
                    "device_id": DEVICE_ID,
                    "token": DEVICE_TOKEN,
                }
            )
            websocket.receive_json()
            start = {
                "type": "recording_start",
                "version": PROTOCOL_VERSION,
                "turn_id": 9,
                "sample_rate_hz": 16000,
                "channels": 1,
                "bits_per_sample": 16,
                "codec": "pcm_s16le",
            }
            websocket.send_json(start)
            websocket.send_bytes(pack_audio_frame(AUDIO_TYPE_MICROPHONE, 9, 0, bytes(PCM_FRAME_BYTES)))
            websocket.send_json({"type": "recording_end", "version": PROTOCOL_VERSION, "turn_id": 9})
            websocket.receive_json()
            websocket.receive_json()
            import time

            time.sleep(0.05)
            websocket.send_json(start)
            response = websocket.receive_json()
    assert response["code"] == "stale_turn"


def test_http_device_status_requires_bearer_token(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        denied = client.get(f"/api/device/{DEVICE_ID}/status")
        accepted = client.get(
            f"/api/device/{DEVICE_ID}/status",
            headers={"Authorization": f"Bearer {DEVICE_TOKEN}"},
        )
    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["connected"] is False


def test_protocol_rejects_invalid_control_json() -> None:
    try:
        parse_control_message('{"type": "hello", "version": "one"}')
    except ValueError as error:
        assert "invalid device control" in str(error)
    else:
        raise AssertionError("invalid device control message was accepted")
