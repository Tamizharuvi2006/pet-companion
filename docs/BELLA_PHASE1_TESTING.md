# Bella Phase 1 validation checklist

## Software checks

- `python -m compileall -q app`
- `python -m pytest -q` (install `requirements-dev.txt` first)
- `pio run -d firmware/bella_esp32`
- `pio run -d firmware/bella_esp32_cam`
- Run the normal browser tests against `/health`, `/metrics`, `/`, `/ws/chat`, `/stt`, `/chat`, `/tts`, and `/talk` without printing `.env`.
- Device protocol simulation: authenticated hello, valid format, binary frame ordering, silent-audio rejection, cancellation, status/config Bearer auth, and stale-turn rejection.

## Physical checks (not implied by software tests)

1. Identify the MCU module/board and actual TFT/camera model before flashing.
2. With power disconnected, audit every GPIO against `BELLA_PHASE1_WIRING.md`: preserve Servo 1 -> GPIO13, Servo 2 -> GPIO12, GPIO21's existing connection, shared I²S BCLK -> GPIO26, and Touch 4 -> GPIO27. Check whether any legacy camera UART still occupies GPIO14/15; do not flash with unresolved conflicts.
3. Identify the exact ESP32 board/module and flash voltage. Inspect GPIO12 external pull-ups/pull-downs and verify its required reset strap level from that board's documentation. Keep GPIO12 Servo 2 disabled unless that audit passes; verify regulated servo/amplifier supply, common ground, module voltage, and no USB/external-supply backfeed.
4. Flash only after device and COM-port confirmation plus explicit approval.
5. Read firmware diagnostics, run microphone RMS/silence tests, then bounded speaker audio at low volume. Check dropped frames and queue overflow.
6. Validate touch debounce, cancel and mute; then VL53L0X reads with known-distance targets and hysteresis.
7. Identify TFT controller/resolution; only then enable its driver and verify non-blocking display updates.
8. Separately identify camera board/sensor, enable its profile, test `/health` and token-authenticated JPEG `/snapshot`, and verify the backend proxy.
9. Test reconnect during listening/speaking and confirm queued/stale audio is cleared.
10. Perform one full physical conversation and record STT, GPT first token, first speaker sample, total duration, and errors from actual logs.

Do not count a successful protocol simulation or compile as audio, sensor, display, servo, camera, or full-conversation acceptance.
