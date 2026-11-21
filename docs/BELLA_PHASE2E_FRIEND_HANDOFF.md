# Bella Phase 2E — Friend Hardware Handoff

This package is for **identification and safe preparation first**. All software candidates compile, but no physical board or display has been identified or tested. Do not flash until the actual labels, controller, flash capacity, wiring, and strap circuitry match a supported profile.

## Included references and local candidate files

- [Supported board/profile matrix](BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md)
- [Corrected wiring and GPIO safety](BELLA_PHASE1_WIRING.md)
- [Step-by-step flashing and provisioning](BELLA_PHASE1_FLASHING.md)
- [One-click setup overview](BELLA_FRIEND_ONE_CLICK_SETUP.md)
- [Physical acceptance checklist](BELLA_PHYSICAL_ACCEPTANCE_CHECKLIST.md)
- [Known limitations](BELLA_KNOWN_LIMITATIONS.md)
- Locally build-verified binary candidates: `artifacts/phase2e/firmware-candidates/`
- Transferable candidate archive: `artifacts/phase2e/BELLA_PHASE2E_UNTESTED_FIRMWARE_CANDIDATES.zip`
- Per-binary sizes and SHA-256 checksums: [release candidate report](BELLA_PHASE2E_RELEASE_CANDIDATE.md#generated-candidate-firmware-package)

Every `.bin` is build-verified but **not physically tested**. The binaries contain no provisioned credentials. The archive is a separate ignored local artifact, not part of a Git commit. Transfer it only with the profile matrix and after identification. Do not choose a file based on appearance or guesswork; first positively identify the board and all connected modules. If a part is not an exact supported match, stop and send its part number/photos to the owner instead of editing source or changing pins. If the friend does not receive the archive, they can build the selected profile from reviewed source after identification.

For an exact supported match, profile selection/build/provisioning requires configuration inputs only—no source-code edits. An unknown or mismatched board is not a supported profile and must stop for owner review.

## Send the owner these identification details first

Take clear photos of the front/back silkscreen and readable labels, with power disconnected. Report:

- Exact ESP32 board/module marking and stated flash capacity; note WROOM/WROVER variant.
- Exact TFT controller, resolution, breakout/variant, flex or module marking, voltage, backlight wiring, and any known ST7735 tab/offset variant.
- Touch-board model and whether TTP223 outputs momentary or toggle/latch behavior; active polarity if documented.
- Microphone, amplifier/speaker, distance sensor, servo models, and any camera PCB/sensor markings.
- All occupied GPIOs and any external pull-up/down resistors on boot-strapping pins.

Never send Wi-Fi passwords, device tokens, camera bearer tokens, or provider keys in photos, chat, logs, or the Hardware Doctor export.

## Preserve this wiring; do not improvise pin changes

| Function | GPIO | Gate |
|---|---:|---|
| Servo 1 | 13 | Firmware disabled by default; do not power/test until mechanism and supply are checked |
| Servo 2 | 12 | Preserve existing wire; disabled and compile-time gated until exact flash/board/reset strap and external pulls are verified |
| Existing unrelated connection | 21 | Reserved; do not move or reuse |
| Shared microphone/speaker I²S BCLK | 26 | Intentional shared clock |
| Touch sensor 4 | 27 | Use only after the planned physical rewire |

Also preserve the full pin map in the wiring guide. GPIO12 is sampled at reset on classic ESP32 parts; the generic board target is not proof of the installed module or flash voltage. Keep Servo 2 disconnected from power during initial reset/flash checks. Firmware's strap gate is a software guard, not electrical verification. Do not generate or enable new servo calibration values in this handoff.

## Build, flash, and provision commands

These are for use **only after the owner confirms the exact profile and wiring**. Replace `COM5` with the positively identified serial port. The build script was run successfully from the project path containing spaces. The flash utility checks that the COM port exists, rebuilds, and requires both `-Flash` and an exact typed confirmation before writing.

```powershell
Set-Location 'D:\final year project\backend'
.\scripts\build-firmware.ps1 -Profile diagnostic
.\scripts\flash-firmware.ps1 -Profile diagnostic -Port COM5 -Flash
.\scripts\provision-device.ps1 -Port COM5
```

Choose one exact display profile only from the matrix: `st7789-240x240`, `ili9341-240x320`, or `st7735-128x160`. Use `touch4-ptt-momentary` only for a physically confirmed momentary TTP223. Camera is a separate optional board; choose `camera-ai-thinker` only for the identified compatible board/sensor and keep camera disabled until secure transport is approved. For other boards, stop rather than selecting the closest-looking profile.

The provisioning utilities hide password/token prompts, do not echo credential values, and transmit only over attached USB serial. **NVS flash encryption is not enabled**, so a person with physical flash access may recover stored Wi-Fi/device credentials. Provision a unique revocable device token; never put an OpenRouter/API key on the device. Camera credentials must be separate from the device token. Use `provision-camera.ps1` only after a separately approved camera bring-up.

## Return evidence for physical acceptance

After identification and only when the owner approves physical testing, send:

1. Board/module and TFT/sensor photos plus exact part/model numbers.
2. Selected profile and build output; state clearly whether a flash actually happened.
3. Sanitized boot/serial log and the sanitized Hardware Doctor report.
4. TFT photos for idle, listening, thinking, speaking, happy, and error; note colors, rotation, offsets, flicker, and frame rate.
5. Microphone status/RMS and a short manually observed test; speaker output heard by a person, with interruptions/clipping/missing audio noted.
6. Touch pad mapping and momentary/toggle behavior; proximity readings as the sensor moves near/far.
7. Servo model and physical safety checklist before any owner-authorized motion test; keep GPIO12 Servo 2 off until strap validation.
8. For a camera, report local/private reachability and TLS route separately; do not expose its plain HTTP port to the Internet.

Do not claim that a simulated event, successful compile, server acknowledgement, or estimated I²S DMA fence proves visible pixels or audible sound.
