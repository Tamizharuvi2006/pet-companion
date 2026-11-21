import json
import struct
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

PROTOCOL_VERSION = 1
AUDIO_TYPE_MICROPHONE = 0x01
AUDIO_TYPE_SPEAKER = 0x02
AUDIO_HEADER = struct.Struct("<BBHII")
AUDIO_HEADER_BYTES = AUDIO_HEADER.size
SAMPLE_RATE_HZ = 16_000
PCM_BITS = 16
CHANNELS = 1
FRAME_DURATION_MS = 40
PCM_FRAME_BYTES = SAMPLE_RATE_HZ * CHANNELS * (PCM_BITS // 8) * FRAME_DURATION_MS // 1000


class DeviceMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: StrictStr = Field(min_length=1, max_length=40)
    version: StrictInt | None = Field(default=None, ge=1, le=255)
    device_id: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    token: StrictStr | None = Field(default=None, min_length=0, max_length=256)
    firmware_version: StrictStr | None = Field(default=None, max_length=32)
    turn_id: StrictInt | None = Field(default=None, ge=0, le=0xFFFFFFFF)
    sequence: StrictInt | None = Field(default=None, ge=0, le=0xFFFFFFFF)
    state: StrictStr | None = Field(default=None, max_length=24)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    sensors: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AudioFrame:
    message_type: int
    version: int
    flags: int
    turn_id: int
    sequence: int
    payload: bytes


def parse_control_message(raw: str) -> DeviceMessage:
    if len(raw.encode("utf-8")) > 4096:
        raise ValueError("control message exceeds 4096 bytes")
    try:
        return DeviceMessage.model_validate_json(raw)
    except ValidationError as error:
        raise ValueError("invalid device control message") from error


def pack_audio_frame(
    message_type: int, turn_id: int, sequence: int, payload: bytes, *, flags: int = 0
) -> bytes:
    if message_type not in (AUDIO_TYPE_MICROPHONE, AUDIO_TYPE_SPEAKER):
        raise ValueError("unknown audio frame type")
    if not 0 <= turn_id <= 0xFFFFFFFF or not 0 <= sequence <= 0xFFFFFFFF:
        raise ValueError("turn_id and sequence must fit unsigned 32-bit fields")
    if not 0 <= flags <= 0xFFFF:
        raise ValueError("flags must fit an unsigned 16-bit field")
    if message_type == AUDIO_TYPE_MICROPHONE and (not payload or len(payload) % 2):
        raise ValueError("PCM16 microphone payload must contain complete samples")
    if len(payload) > PCM_FRAME_BYTES:
        raise ValueError("audio frame payload exceeds the 40 ms protocol limit")
    return AUDIO_HEADER.pack(message_type, PROTOCOL_VERSION, flags, turn_id, sequence) + payload


def parse_audio_frame(data: bytes, *, max_payload_bytes: int) -> AudioFrame:
    if len(data) < AUDIO_HEADER_BYTES:
        raise ValueError("audio frame is shorter than its header")
    if len(data) > AUDIO_HEADER_BYTES + max_payload_bytes:
        raise ValueError("audio frame exceeds the configured size limit")
    message_type, version, flags, turn_id, sequence = AUDIO_HEADER.unpack_from(data)
    if message_type != AUDIO_TYPE_MICROPHONE:
        raise ValueError("device may only upload microphone PCM frames")
    if version != PROTOCOL_VERSION:
        raise ValueError("unsupported audio protocol version")
    if flags != 0:
        raise ValueError("unsupported audio frame flags")
    payload = data[AUDIO_HEADER_BYTES:]
    if not payload or len(payload) % 2:
        raise ValueError("microphone PCM payload must contain complete 16-bit samples")
    if len(payload) > PCM_FRAME_BYTES:
        raise ValueError("microphone frame exceeds the 40 ms protocol limit")
    return AudioFrame(message_type, version, flags, turn_id, sequence, payload)


def decode_control_json(raw: str) -> dict[str, Any]:
    """Small helper for callers that need an untyped nested event payload."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("invalid JSON control message") from error
    if not isinstance(value, dict):
        raise ValueError("control message must be a JSON object")
    return value
