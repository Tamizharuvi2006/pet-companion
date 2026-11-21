# Bella device protocol v1

## Transport and authentication

The DevKit opens a WebSocket to `/ws/device`. It sends a `hello` JSON message as the first WebSocket message within five seconds:

```json
{"type":"hello","version":1,"device_id":"device-001","token":"<per-device-random-token>","firmware_version":"0.1.0","capabilities":{"audio_in":true,"audio_out":true,"touch":true,"distance":true,"tft":false,"servos":false},"sensors":{}}
```

By default, the token is compared against `BELLA_DEVICE_TOKENS` on the server and is never put in a URL. For a temporary presentation only, the owner may set `BELLA_DEVICE_AUTH_REQUIRED=false`; then a valid `device_id` can connect with an empty token. This makes the public `/ws/device` endpoint open to any internet client and can incur provider charges, so restore `true` after the demo. Use `ws://` only on a protected development LAN. For remote access, use `wss://` with certificate verification enabled and a rotated, unique token per device. Do not log the hello payload.

## Control messages

All JSON control messages carry `type` and `version: 1`. Supported client messages are `hello`, `recording_start`, `recording_end`, `cancel`, `sensor_event`, and `ping`; caption-capable firmware also sends `display_settings_ack`. The server returns `device_ready`, `transcript`, `reply_delta`, `display_settings`, `tts_chunk_start`, `tts_chunk_end`, `turn_complete`, `error`, and `pong`.

`recording_start` declares the input format exactly:

```json
{"type":"recording_start","version":1,"turn_id":42,"sample_rate_hz":16000,"channels":1,"bits_per_sample":16,"codec":"pcm_s16le"}
```

`recording_end`, `cancel`, and audio frames must use the same active `turn_id`. Audio sequence numbers start at zero and increase by one. Every new turn uses a new monotonically increasing unsigned 32-bit ID. Only one turn may be active per device. Keep sending `ping` periodically (firmware target: every 10 seconds); the backend closes idle device sockets after 45 seconds.

## Binary audio frame

Every binary WebSocket message contains exactly one frame. Header is 12 bytes, little-endian, `struct.Struct("<BBHII")`:

| Offset | Size | Field | Value |
|---:|---:|---|---|
| 0 | 1 | type | `0x01` microphone upload, `0x02` speaker playback |
| 1 | 1 | version | `0x01` |
| 2 | 2 | flags | `0` in v1 |
| 4 | 4 | turn_id | unsigned 32-bit active turn |
| 8 | 4 | sequence | unsigned 32-bit sequence (speaker restarts at each TTS chunk) |
| 12 | up to 1280 | payload | PCM signed 16-bit LE, mono, 16 kHz |

The normal payload is 1,280 bytes = 640 samples = 40 ms. The final frame may be shorter but must contain whole 16-bit samples. Backend limits are configurable and validated. The server accepts only microphone frames from the device; the device accepts only speaker frames from the server.

For speaker data, the server sends `tts_chunk_start` before the first binary frame and `tts_chunk_end` after the last frame. `chunk_id` associates each synthesized output with its metadata; frame sequence is scoped to the chunk. The device must discard frames with stale turn IDs, and clear its bounded playback queue on cancel or disconnect. Control and binary frames share one ordered WebSocket; device firmware must process them in order.

## Streaming text and display captions

The device sends `caption_overlay_v1: true` and its persisted
`display_captions_enabled` state in `hello.capabilities`. For GPT Audio Mini
turns, every assistant text delta is sent as `reply_delta` with the active
`turn_id`; the firmware may show it as it arrives. It must not display the user
`transcript` as Bella's reply. The face animation continues independently. The
caption overlay is visible only while playback is active and is cleared when
playback drains, is cancelled, or enters an error state.

To change the preference, the server sends:

```json
{"type":"display_settings","version":1,"turn_id":42,"command_id":"<32 hex chars>","captions_enabled":false}
```

The ESP32 applies the setting immediately, clears any old caption, stores it in
NVS, and responds with `display_settings_ack` containing the setting and a
`persisted` boolean. If NVS saving fails, it remains active only for the current
boot and reports `persisted:false`. Firmware without `caption_overlay_v1` must
not be told by the backend that the voice command succeeded.

## Runtime behavior

DevKit sends PCM frames while Touch 1 is held/toggled to listening, then sends `recording_end`. The backend rejects oversized/out-of-order input, applies an RMS silence check, wraps PCM in WAV for the configured OpenRouter STT path, retains local Faster-Whisper fallback, and streams reply text/audio using the configured default voice engine. In the GPT Audio Mini device path, the provider emits mono 24 kHz PCM; the backend incrementally resamples it to the device's 16 kHz wire format. The browser route `/ws/chat` remains a separate WebM protocol and is not changed into a device protocol.

## Status APIs

- `GET /api/device/{device_id}/status` — Bearer-authenticated device snapshot.
- `GET /api/device/{device_id}/config` — Bearer-authenticated protocol/audio limits.
- `POST /api/device/{device_id}/camera/capture` — Bearer-authenticated proxy to the one backend-configured camera snapshot URL; callers cannot pass a URL.

The registry is in process memory. It is diagnostic, not durable, and is reset when the backend process restarts.
