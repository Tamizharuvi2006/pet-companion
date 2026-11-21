# Bella Physical Acceptance Checklist

Record the exact part numbers, observations and evidence. Keep every item unchecked until it is actually tested. Firmware builds, simulated device events and the Hardware Doctor alone are not physical acceptance.

## A. Identify and inspect (power disconnected)

- [ ] ESP32 module/board part number, flash capacity, and any PSRAM identified.
- [ ] TFT controller, native resolution, ST7735 tab/offset variant if applicable, voltage and backlight wiring identified.
- [ ] INMP441 and MAX98357A part numbers, speaker impedance/power, and supply requirements identified.
- [ ] TTP223 module mode (momentary/toggle) and output polarity confirmed.
- [ ] VL53L0X board/pin labels and supply/logic levels confirmed.
- [ ] Servo models, external supply/current, and neutral pulse ranges confirmed. GPIO12 external pulls/reset level checked against the exact ESP32 board/module documentation.
- [ ] Optional camera PCB and sensor identified; camera pins are on the separate board.
- [ ] Photos or schematic show no accidental use of GPIO21 and no changed pin mapping.

## B. Wiring/power review

- [ ] TFT: CS/RST/DC = 5/4/2; MOSI/SCK/MISO = 23/18/19; backlight remains disconnected until its polarity/GPIO is known.
- [ ] INMP441: BCLK/WS/SD = 26/25/34; mic channel select matches the firmware’s left-slot assumption.
- [ ] MAX98357A: BCLK/LRC/DIN = 26/25/22; shared clocks are intentional.
- [ ] Touch 1–4 = 32/33/14/27; Touch 4 has the requested physical rewiring.
- [ ] VL53L0X SDA/SCL = 16/17.
- [ ] Servo 1 = 13; Servo 2 = 12 but signal/power remain disconnected until strap and power checks pass. GPIO21 remains reserved.
- [ ] Common ground and all supply voltages/current limits reviewed from module datasheets. No GPIO is driven above the board’s allowed logic voltage.
- [ ] Classic ESP32 strap levels on GPIO0/2/5/12/15 reviewed with all attached modules before flashing or rebooting; GPIO4 TFT-reset pulls checked separately.

## C. Firmware, provisioning and connection

- [ ] Record chosen profile and reason it matches the physical module.
- [ ] Build command succeeded; record toolchain and artifact hash/path.
- [ ] Flash exact COM port only after operator confirmation; board boots repeatedly with peripherals attached.
- [ ] USB provisioning accepted Wi-Fi, exact `wss://.../ws/device`, device ID and server-matched device token; no secret appears in serial output.
- [ ] Wi-Fi and authenticated Railway WebSocket reconnect after router interruption.
- [ ] `/doctor.html` identifies the correct authenticated device and yields a sanitized report.
- [ ] Firmware profile, display init, frame counters, touch counters, distance evidence, I²S readiness, and safety-gate state recorded.

## D. Display and local interactions

- [ ] Eye image is visible, upright, correct colors/orientation, and not clipped; backlight safe and stable.
- [ ] Idle, listening, thinking, speaking, offline, error and transitions are inspected on the actual display.
- [ ] Touch 1 Happy, Touch 2 Love, Touch 3 Curious, Touch 4 Wink short press work with debounce.
- [ ] All four pads release cleanly; no repeated or overlapping gestures.
- [ ] If verified momentary TTP223 and explicitly selected, hold Touch 4 longer than threshold starts one PTT turn; release ends it. Short tap remains Wink. Otherwise PTT profile stays disabled.
- [ ] VL53L0X reports valid range; test presence entry/exit around configured 700/900 mm thresholds and invalid/out-of-range rejection.
- [ ] Local touch/proximity expressions continue while Railway is disconnected; they do not call paid AI or move servos.

## E. Microphone, speaker and cloud voice

- [ ] Quiet-room spoken test: the mic RMS rises from idle; confirm complete 16 kHz mono PCM frame transfer and expected transcript.
- [ ] Test silence and background noise; silence does not create an unwanted paid request.
- [ ] Confirm max recording duration, explicit start/stop, cancellation, disconnect behavior and no stale audio replay.
- [ ] Confirm text/audio chunk order, no missing/repeated phrases, no clipping/underruns and no unexpected pauses.
- [ ] Listen at the physical speaker and mark audible success separately from `i2s_write_accepted`/estimated DMA fence.
- [ ] Check bounded speaker queue/drop counts over repeated turns; no long-run heap/task failure.
- [ ] Real AI/STT/TTS tests are separately authorized and cost-bounded by the owner; Hardware Doctor does not make them.

## F. Servo and camera (optional, explicitly gated)

- [ ] Servo power remains disconnected until the board strap review and independent servo power plan pass.
- [ ] GPIO12 strap/startup measured before any Servo 2 enable; if the exact safe state cannot be established, Servo 2 stays off.
- [ ] Servo 1/2 motion is not accepted from compile flags alone; calibration, end stops, current and reset behavior are physically measured.
- [ ] Camera board profile, sensor, local power and isolated network path confirmed. No public plaintext HTTP exposure.
- [ ] One frame only after explicit owner action; verify no background/automatic capture.

## G. Final evidence to send the owner

- [ ] Sanitized Hardware Doctor JSON.
- [ ] Profile, exact board/controller/module IDs, wiring diagram/photo without credentials, and firmware hash.
- [ ] Per-step PASS/FAIL/NOT TESTED notes, serial error codes without secrets, audio observations, display observations, range readings and reset behavior.
- [ ] Outstanding safety issues and anything left disabled.
