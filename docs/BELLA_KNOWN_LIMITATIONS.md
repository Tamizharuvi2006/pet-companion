# Bella Known Limitations and Open Hardware Gates

## Must be resolved by physical identification or test

- The physical ESP32 board/module and flash size are not known. `esp32dev` is only the PlatformIO compile target.
- The TFT controller, exact native resolution, ST7735 tab/offset variant, backlight pin/polarity, and power tolerance are unknown. Build success does not mean pixels are visible. A controller outside the declared ST7789 240×240, ILI9341 240×320 or ST7735 128×160 profile needs an exact driver/profile change.
- On the classic ESP32, GPIO2/5/12/MTDI/15 are boot strapping pins; GPIO4 is not a strapping pin but remains the TFT reset assignment and must be checked for breakout pulls. GPIO12 Servo 2 must remain disabled until exact chip/module, flash voltage, board external pulls and reset waveform are reviewed. GPIO21 remains reserved.
- Touch 4’s GPIO27 wiring change and every sensor’s polarity/voltage are not measured. Push-to-talk is off by default; its optional profile only supports a confirmed momentary TTP223, not toggle/latch output.
- INMP441 channel select, microphone gain/noise, MAX98357A wiring, speaker impedance/power, I²S acoustic output and audible timing need a physical test.
- The VL53L0X needs an actual valid ranging test; its 700/900 mm entry/exit thresholds are configurable software defaults, not a calibrated enclosure range.
- Servo outputs are intentionally disabled and there is no remote movement or calibration command path. Hardware-specific neutral/end-stop pulse limits cannot be chosen safely before the exact servo model and mechanism are identified; no external power should be connected for casual testing. If servos are required for the first hardware demo, model-specific calibration/control software remains an owner task before activation.

## Camera

- Camera is a separate, optional ESP32-CAM board. The AI-Thinker profile is not a confirmed board or sensor.
- Camera-board Wi-Fi and bearer token use the local USB provisioning flow and separate `bella_cam` NVS namespace; NVS flash encryption is not enabled, so physical flash access can recover values.
- The camera board itself serves plaintext HTTP. The backend accepts that only for private/loopback development; public mode requires an HTTPS gateway/tunnel with a reachable private route. Railway cannot usually reach a private LAN IP directly. Keep the feature disabled until that path is deliberately configured; do not expose camera port 80 publicly.
- No physical camera capture, face recognition, emotion model or automatic capture is implemented/accepted in Phase 2D.

## Voice and runtime

- The Python suite and fake providers validate offline protocol behavior, not OpenRouter latency, provider accuracy/cost, real microphone capture, human-perceived speaker start, or uninterrupted physical playback. Any live paid request needs separate explicit budget/authorization.
- The device `playback_drained` fence is an estimated I²S DMA/ring completion. It does not prove that the MAX98357A emitted sound or that the listener heard the whole phrase.
- Device registry state is process-local. Railway must use one worker/replica unless shared state/session ownership is designed and tested.
- The main ESP32 stores Wi-Fi and device credentials in NVS without flash encryption. USB provisioning avoids source files/log output, but physical flash access may reveal stored values. Use a dedicated/revocable token and physical access controls.
- TFT rendering is bounded by an internal tile buffer and does not use a full-screen framebuffer, but actual frame rate, SPI stability, heap headroom and contention on the selected physical board remain unmeasured.
- Offline image snapshots are generated from the normalized software renderer. They do not prove real display color order, gamma, panel offsets, rotation, backlight or pixel-perfect parity with Face Studio.

## What is explicitly not done

- No `.env` change/readout, provider request, Railway deploy, Git push, port restart, hardware flash, servo activation or physical camera capture.
- No hardware is claimed PASS based on a simulator, firmware compile, or authenticated hello alone.
- Do not delete or reset any local build/dependency artifacts to “clean up” this workspace; inspect `git status` and preserve pre-existing user changes.
