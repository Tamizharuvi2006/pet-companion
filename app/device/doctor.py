"""Evidence-based Hardware Doctor summaries; never infer acoustic/display success."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _error_category(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return {
        "TimeoutError": "timeout",
        "ReadTimeout": "upstream_timeout",
        "ConnectError": "network_connect_error",
        "HTTPStatusError": "upstream_http_error",
        "ValueError": "validation_error",
        "RuntimeError": "runtime_error",
        "WebSocketDisconnect": "connection_closed",
        "device_playback_error": "device_playback_error",
    }.get(value, "unspecified_error")


def _check(status: str, detail: str, evidence: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "detail": detail}
    if evidence is not None:
        result["evidence"] = evidence
    return result


def build_hardware_doctor(record: dict[str, Any] | None, device_id: str) -> dict[str, Any]:
    """Classify only reported device evidence; missing readings stay PENDING."""
    record = record or {"device_id": device_id, "connected": False, "capabilities": {}, "sensors": {}}
    capabilities = record.get("capabilities") if isinstance(record.get("capabilities"), dict) else {}
    sensors = record.get("sensors") if isinstance(record.get("sensors"), dict) else {}
    connected = record.get("connected") is True
    has_history = bool(record.get("last_heartbeat"))
    last_heartbeat = record.get("last_heartbeat")
    heartbeat_age: float | None = None
    if isinstance(last_heartbeat, str):
        try:
            heartbeat_age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(last_heartbeat)).total_seconds())
        except ValueError:
            heartbeat_age = None
    if connected:
        connection = _check("PASS", "Authenticated device WebSocket is connected", "device hello accepted")
    elif has_history:
        connection = _check("FAIL", "Device was seen before but is currently disconnected")
    else:
        connection = _check("PENDING", "No authenticated device connection has been observed")

    heartbeat = _check("PASS", "Recent device heartbeat", round(heartbeat_age, 1)) if connected and heartbeat_age is not None and heartbeat_age <= 35 else (
        _check("FAIL", "Heartbeat is stale or unavailable while marked connected", heartbeat_age)
        if connected else _check("PENDING", "Heartbeat requires a connected device", heartbeat_age)
    )
    firmware = record.get("firmware_version")
    firmware_check = _check("PASS", "Firmware reported by authenticated device", firmware) if isinstance(firmware, str) and firmware not in {"", "unknown"} else _check("PENDING", "Firmware version not reported")

    display_profile = capabilities.get("tft_profile") or sensors.get("display_profile")
    display_initialized = _bool(sensors.get("display_initialized"))
    display_frames = _number(sensors.get("display_frames"))
    if display_profile in {None, "diagnostic-disabled"}:
        display_bus = _check("UNSUPPORTED", "TFT driver is disabled until the controller and module profile are identified", display_profile)
    elif display_initialized is True and display_frames is not None and display_frames > 0:
        display_bus = _check("PASS", "Selected driver initialized and reports completed frame transfers; visible pixels/backlight still need physical inspection", {"profile": display_profile, "frames": int(display_frames)})
    elif display_initialized is False and connected:
        display_bus = _check("FAIL", "Selected TFT profile failed initialization", display_profile)
    else:
        display_bus = _check("PENDING", "TFT driver transfer evidence is not available", display_profile)

    seen_mask = _number(sensors.get("touch_seen_mask"))
    touch_checks = {}
    for pad in range(1, 5):
        seen = seen_mask is not None and int(seen_mask) & (1 << (pad - 1)) != 0
        touch_checks[f"touch_{pad}"] = _check("PASS", "A debounced press was reported by the device", pad) if seen else _check("PENDING", "Press this pad once during physical acceptance", pad)

    distance_ready = _bool(sensors.get("distance_initialized"))
    distance_valid = _bool(sensors.get("distance_valid"))
    distance_samples = _number(sensors.get("distance_valid_samples"))
    if distance_ready is False and connected:
        distance = _check("FAIL", "VL53L0X initialization failed")
    elif distance_ready is True and distance_valid is True and (distance_samples or 0) > 0:
        distance = _check("PASS", "Ranging initialized and at least one valid measurement was reported", {"mm": _number(sensors.get("distance_mm")), "samples": int(distance_samples or 0)})
    else:
        distance = _check("PENDING", "Sensor requires physical connection and a valid range sample")

    input_ready = _bool(sensors.get("i2s_input_ready"))
    mic_frames = _number(sensors.get("mic_frames")) or 0
    mic_rms = _number(sensors.get("mic_last_rms"))
    if input_ready is False and connected:
        microphone = _check("FAIL", "I²S microphone input initialization failed")
    elif input_ready is True and mic_frames > 0 and mic_rms is not None and mic_rms >= 12:
        microphone = _check("PASS", "I²S input produced a non-silent frame during an explicit recording", {"rms": int(mic_rms), "frames": int(mic_frames)})
    elif input_ready is True:
        microphone = _check("PENDING", "I²S initialized; use explicit push-to-talk and confirm a level reading")
    else:
        microphone = _check("PENDING", "Microphone has not reported initialization")

    output_ready = _bool(sensors.get("i2s_output_ready"))
    playback_status = record.get("playback_status")
    playback_basis = record.get("playback_basis")
    error_category = _error_category(record.get("last_error"))
    if output_ready is False and connected:
        speaker = _check("FAIL", "I²S speaker output initialization failed")
    elif output_ready is True and playback_status == "drained":
        speaker = _check("PASS", "Device reported an estimated I²S drain fence; listener must still confirm audible output", playback_basis)
    elif output_ready is True:
        speaker = _check("PENDING", "I²S output initialized; audible output requires a physical listening test")
    else:
        speaker = _check("PENDING", "Speaker output has not reported initialization")

    camera_available = _bool(sensors.get("camera_available"))
    if camera_available is True:
        camera = _check("PASS", "A camera snapshot was captured and proxied")
    elif capabilities.get("camera") == "separate_board_optional":
        camera = _check("PENDING", "Optional separate camera board is not connected to this ESP32 report")
    else:
        camera = _check("UNSUPPORTED", "Camera capability is not enabled in this firmware profile")

    servo1 = _bool(sensors.get("servo_enabled"))
    servo2 = _bool(sensors.get("servo2_gpio12_enabled"))
    servo2_gate = _bool(sensors.get("servo2_gpio12_strap_gate_open"))
    if servo1 is False and servo2 is False and servo2_gate is False:
        servo = _check("PASS", "Servo PWM is disabled and GPIO12 safety gate is closed")
    elif servo2 is True and servo2_gate is not True:
        servo = _check("FAIL", "Unsafe Servo 2 configuration reported; keep power disconnected")
    else:
        servo = _check("PENDING", "Servo signals require verified board, power, neutral limits and explicit calibration")

    checks = {
        "connection": connection,
        "heartbeat": heartbeat,
        "firmware": firmware_check,
        "display_bus": display_bus,
        "display_visible": _check("PENDING", "A successful transfer cannot prove the panel image or backlight is physically visible"),
        **touch_checks,
        "distance": distance,
        "microphone": microphone,
        "speaker_i2s": speaker,
        "speaker_audible": _check("PENDING", "Audible output can only be confirmed by a person at the speaker"),
        "last_error": _check("FAIL", "A server/device error was recorded; raw detail is withheld", error_category)
        if error_category else _check("PASS", "No error is currently recorded"),
        "camera": camera,
        "servo_safety": servo,
    }
    statuses = {check["status"] for check in checks.values()}
    overall = "FAIL" if "FAIL" in statuses else "PENDING" if statuses.intersection({"PENDING", "UNSUPPORTED"}) else "PASS"
    # Include only known-safe, non-text evidence. Never export transcript, token, URL, or raw error strings.
    sanitized = {
        "device_state": record.get("state") if isinstance(record.get("state"), str) else "UNKNOWN",
        "tft_profile": display_profile,
        "display_initialized": display_initialized,
        "display_frames": int(display_frames) if display_frames is not None else None,
        "touch_seen_mask": int(seen_mask) if seen_mask is not None else None,
        "distance_mm": _number(sensors.get("distance_mm")),
        "distance_valid_samples": int(distance_samples) if distance_samples is not None else None,
        "mic_last_rms": int(mic_rms) if mic_rms is not None else None,
        "mic_frames": int(mic_frames),
        "audio_dropped_frames": _number(sensors.get("audio_dropped_frames")),
        "servo_enabled": servo1,
        "servo2_gpio12_enabled": servo2,
        "camera_available": camera_available,
        "playback_status": playback_status if isinstance(playback_status, str) else "not_reported",
        "playback_basis": playback_basis if isinstance(playback_basis, str) else None,
        "last_error_category": error_category,
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "device_id": device_id,
        "overall": overall,
        "evidence": "authenticated device reports only; SIMULATED events are not hardware pass results",
        "checks": checks,
        "sanitized_device_data": sanitized,
    }
