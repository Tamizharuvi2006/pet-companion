# Friend's Bella hardware handoff

No hardware was flashed or physically validated. Do not guess the display driver.

## Parts and wiring from source configuration

ESP32 development-module profile (actual board/flash must be confirmed), INMP441 microphone, MAX98357A amplifier/speaker, four TTP223 pads, TFT of unknown controller/resolution, VL53L0X, and two planned servos. ESP32-CAM is a separate existing project, not activated in this phase.

| Connection | Source-configured GPIO |
| --- | --- |
| TFT CS / reset / DC | 5 / 4 / 2 |
| TFT MOSI / SCLK / MISO | 23 / 18 / 19 |
| Shared I2S BCLK / WS | 26 / 25 |
| Microphone data / speaker data | 34 / 22 |
| Touch 1 / 2 / 3 / 4 | 32 / 33 / 14 / 27 |
| VL53L0X SDA / SCL | 16 / 17 |
| Servo 1 / Servo 2 | 13 / 12; disabled by default |
| GPIO21 | Reserved for existing physical connection; do not repurpose |

These are source assignments, not verified physical wiring. For a connector-by-connector sheet, see [`BELLA_FRIEND_PIN_CONNECTIONS.md`](BELLA_FRIEND_PIN_CONNECTIONS.md). Touch4 must actually be rewired to GPIO27. Confirm TFT controller, dimensions, rotation, supply/logic levels and SPI compatibility before enabling rendering. GPIO2 and GPIO5 are classic ESP32 strapping pins; review their reset pulls. GPIO4 is the TFT reset line and its breakout pull still needs checking. GPIO12/MTDI can select flash voltage at reset: verify exact board/flash voltage and external pull-ups before enabling Servo2. Keep all servo enable/safety flags off during this handoff. Check the complete physical occupied-pin list before flashing.

## Configure and build

1. Install PlatformIO Core or the PlatformIO IDE extension. The compile target is `esp32dev` with a nominal 4 MB flash partition; confirm the actual board and flash capacity before flashing.
2. The main firmware uses the USB provisioning/NVS workflow; do **not** copy `secrets.h.example` or edit C++ to set credentials. Keep TLS verification enabled and use the exact `wss://<developer-host>/ws/device` endpoint.
3. From the repository root, choose `diagnostic` unless the friend has positively identified a matching display. The helper creates/removes its own temporary drive alias to handle workspace paths with spaces:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build-firmware.ps1 -Profile diagnostic
```

4. **Only after wiring/board review and the hardware owner's approval**, flash the detected COM port. This script requires `-Flash`, validates the port and asks for a typed confirmation before uploading:

```powershell
.\scripts\flash-firmware.ps1 -Profile diagnostic -Port COM7 -Flash
```

5. After the firmware boots, provision Wi-Fi and the device-only Railway credential over the attached USB serial link. Password/token prompts are hidden:

```powershell
.\scripts\provision-device.ps1 -Port COM7
```

The exact profile matrix, complete no-code handoff and NVS reset recovery are in `BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md` and `BELLA_FRIEND_ONE_CLICK_SETUP.md`.

## First connection checks

Power safely; confirm Wi-Fi connects, then serial reports authenticated device session ready. Developer signs into hosted `/face.html`, selects Connected Device mode and sees presence/heartbeat. Touch pads should map to happy/love/curious/wink without voice requests or servo movement. Dashboard distinguishes conversation state and reported face state.

The face engine uses a bounded latest-event queue. The diagnostic profile leaves the display driver disabled; explicit ST7789/ILI9341/ST7735 candidates are available but are not physical validation. Do not infer visible pixels from a build or engine acknowledgement. Open owner-authenticated `/doctor.html` for device evidence, then test losing/recovering Wi-Fi and backend connectivity. Do not run paid voice tests without the developer's separate authorization.

Return: actual board and flash marking, TFT controller/resolution/rotation, redacted build/boot and connection logs, per-pad results, disconnect/reconnect behavior and any reset failures. Never send tokens/passwords, ignored configuration files or unredacted auth payloads.

## Phase 2C playback/face evidence

Phase 2C adds a final speaker queue marker and DMA callback fence. Serial/dashboard `playback_started` is based on an accepted I²S write and is estimated. `playback_drained` uses a conservative DMA ring fence; it is not proof that the amplifier produced sound. `turn_complete` from the server only means server-side work ended. Report interruptions, DMA timeouts and any unexpected audio after cancellation separately.

During separately authorized hardware voice testing, return the active turn IDs, ordered playback acknowledgments, whether the speaker actually started/stopped, whether speech was complete/duplicated, and any shared-clock recording disturbance when playback is cancelled. Do not label a synthetic fence test or successful firmware build as speaker acceptance.

## GPT Audio Mini and reply captions

The default voice engine is configured by the Railway variable
`VOICE_ENGINE_DEFAULT=gpt_audio_mini`. It keeps one authenticated `/ws/device`
service and the existing pin map. Device turns still use the configured
OpenRouter STT model for transcription; GPT Audio Mini generates the streamed
reply text and audio. The 24 kHz model audio is converted to the established
16 kHz speaker format. Browser and device transport remain separate protocols.

The latest caption-capable firmware advertises `caption_overlay_v1`. The display
continues animating its face; when captions are on, each assistant text delta
appears over the face only while Bella's speaker audio is playing. Captions
default on and persist in NVS. The user can say “captions off” / “face only” to
hide text or “captions on” / “show captions” to restore it. The firmware's
current built-in font is Latin-only, so universal non-Latin on-screen captions
are not implemented. Voice language recognition and synthesis also need
language-by-language acceptance; do not claim that every language works.

Offline firmware builds and mock tests do not validate a real provider stream,
the friend’s microphone/speaker, or pixels on the identified display. OpenAI's
current GPT Audio Mini model page marks it deprecated and says streaming is not
supported, while OpenRouter still lists the model. Verify actual availability
and stream behavior in the deployment account before treating this as a stable
release dependency. See [`BELLA_VOICE_ENGINE_COMPARISON.md`](BELLA_VOICE_ENGINE_COMPARISON.md).

Offline touch now temporarily displays its local reaction while retaining a separate offline indicator in normalized geometry. Network telemetry is bounded/asynchronous, so it can be absent during an outage without blocking local animation. Touch 4 remains short-tap Wink by default; the optional PTT profile is only for confirmed momentary TTP223 mode. See `BELLA_PHASE2C_PROTOCOL.md` for event meanings.
