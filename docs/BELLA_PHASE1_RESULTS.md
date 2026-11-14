# Bella Phase 1 status report

## Implemented in source

- Added a separate authenticated `/ws/device` route and authenticated device status/config/camera-proxy routes. Existing browser `/ws/chat` remains routed separately and calls the same existing shared stream turn service.
- Defined v1 JSON control messages and a 12-byte little-endian audio frame header. Device audio is mono PCM16LE/16 kHz; server-side FFmpeg converts the already-generated TTS file to bounded PCM frames.
- Reuses existing OpenRouter STT + local Faster-Whisper fallback, GPT streaming, session memory, and TTS provider (including the existing Kokoro/Edge race). No additional model/API request is created for conversion.
- Added an in-memory device registry, safe per-device bearer/hello token checks, recording limits, audio sequence validation, silent-audio guard, and tests for protocol/auth/pinmap/device silence behavior.
- Added separate ESP-IDF/PlatformIO projects for the main ESP32 and ESP32-CAM. Main firmware uses modern I²S, Wi-Fi/WebSocket, audio queues, touch input, distance-sensor code, and diagnostics. GPIO12 is Servo 2, GPIO21 is reserved, and GPIO26 remains shared I²S BCLK. Servo output is disabled by default; Servo 2 has an additional GPIO12 strap-confirmation build guard. TFT rendering and the camera profile remain disabled pending exact board/module identification.

## Evidence and limits

- Backend validation: `python -m compileall -q app tests` passed and `python -m pytest -q tests` passed **11 tests**. The suite includes health/metrics and simulated device protocol/authentication/pin-conflict cases; it does not emulate real sensors or audio hardware. Pytest reports two dependency deprecation warnings.
- After correcting Servo 2 to GPIO12 and reserving GPIO21, the default main ESP32 firmware build passed again; servo outputs remain disabled. RAM 18,816 bytes (5.7%), app flash 250,477 bytes of 3,145,728 (8.0%).
- Main ESP32 firmware: PlatformIO build **passed** using ESP-IDF 6.0.1 / Espressif32 7.0.1 / `esp32dev`; RAM 18,816 bytes (5.7%), app flash 250,477 bytes of 3,145,728 (8.0%).
- ESP32-CAM firmware: PlatformIO build **passed** with the camera profile disabled; RAM 13,668 bytes (4.2%), app flash 161,605 bytes of 3,145,728 (5.1%). This validates the default disabled-camera firmware build, not image capture.
- The checkout path contains spaces, which caused PlatformIO to reject the original project path. Both builds were therefore run from temporary no-space validation copies of the firmware source. No source edits were made only in those copies.
- The pin map is derived from the supplied request, not physical inspection. No serial COM port or positively identified board was available.
- The source pin audit reports GPIO21 as reserved and intentionally unused. GPIO14 is assigned to Touch 3, so any still-attached legacy camera UART on GPIO14 would conflict; GPIO15 is not assigned by Bella but is also an ESP32 strap pin. Physical wiring status for these pins must be inspected before flashing.
- PlatformIO still targets generic `esp32dev` with a 4 MB partition layout. The exact physical ESP32 variant and flash voltage have not been confirmed, so the GPIO12 reset strap and target flash settings remain a hardware acceptance blocker.
- No board was flashed and no peripheral was powered. Microphone, speaker, touch, distance, TFT, servo, camera capture, reconnect, and end-to-end conversation behavior remain physically unverified. Servos and camera are disabled by default pending board/wiring confirmation.

## Current status vocabulary

- **Implemented:** source/config/docs/tests are present.
- **Compiled/tested:** confirmed for both default firmware builds and the 10-test backend suite above.
- **Simulated:** software protocol path tested without hardware.
- **Physically verified:** only after actual board/module operation.
- **Blocked:** exact hardware identification, wiring correction, power confirmation, COM port, and approval for flashing remain required.
