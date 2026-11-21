# Bella Phase 2D — Software Completion and Evidence

Date: 2026-11-15
Scope: local software/firmware preparation only. No paid provider calls, `.env` edits, deployment, Git push, server restart, or device flash were performed.

## Outcome

The project now has a bounded physical TFT renderer path, diagnostic/provisioning tools, local sensor/audio telemetry, an owner-authenticated Hardware Doctor, and USB/NVS provisioning for both the main board and optional camera board. Firmware/controller profiles are build candidates only. Exact board, display module, TTP223 mode, camera board, power, and wiring still need physical identification and acceptance.

| Area | Phase 2D classification | Evidence / boundary |
|---|---|---|
| Browser face, expression and playback synchronization | SOFTWARE COMPLETE — OFFLINE VERIFIED | Existing Phase 2C behavior preserved; browser tests and full suite listed below |
| Device WebSocket, voice PCM, bounded recording and estimated playback fence | READY FOR PHYSICAL TEST | Offline synthetic device turn is covered; speaker acoustics and real device timing are not |
| Provisioning and secure backend URL validation | SOFTWARE COMPLETE — OFFLINE VERIFIED | UART/NVS flow plus native WSS URL policy tests; serial hardware not exercised |
| Touch, local expressions and proximity hysteresis | READY FOR PHYSICAL TEST | GPIO assignments preserved; pad polarity, TTP223 momentary/toggle mode, sensor orientation and range need hardware confirmation |
| ST7789 240×240, ILI9341 240×320, ST7735 128×160 | READY FOR PHYSICAL TEST | Candidate firmware profiles compile; no panel/controller has been identified or visually tested |
| Unknown/other TFT variants and backlight | BLOCKED BY UNKNOWN HARDWARE | The backlight GPIO and ST7735 tab/offset variant are unknown; no auto-detection is attempted |
| Servo outputs | OPTIONAL / DISABLED | Default firmware keeps both servos off; GPIO12/Servo 2 remains gated. Exact model-specific pulse calibration and physical movement acceptance are still pending |
| Separate ESP32-CAM board | OPTIONAL / DISABLED | AI-Thinker and disabled firmware profiles compile; Wi-Fi/token use local serial-to-NVS provisioning; exact PCB/sensor and safe remote network path remain unverified |
| Railway device integration | READY FOR PHYSICAL TEST | Authenticated WSS protocol and release checklist are ready; no Railway deployment or live device connection was attempted |

## Implemented in this pass

- `firmware/bella_esp32/src/display.cpp` now initializes the explicitly selected `esp_lcd` profile and draws the existing normalized face geometry into a small internal DMA tile. It waits for transfer completion before reusing that tile. Diagnostic remains the default profile.
- Candidate profiles declare controller, resolution, 26 MHz SPI, RGB565, rotation 0, backlight behavior, and tile memory in `firmware/bella_esp32/include/bella_tft_profile.h`.
- Deterministic 240×240 offline snapshots were rendered from the embedded pixel renderer. They demonstrate renderer output, not a physical panel or pixel-perfect browser match.
- Device Wi-Fi, backend WSS URL, device ID and token now come from the USB provisioning/NVS path rather than compile-time credential macros. The firmware checks the provisioned URL—not the obsolete compile-time placeholder—and accepts only the fixed WSS device endpoint.
- The Windows provisioning utility has hidden password/token prompts, no credential echo, and a separately confirmed namespace-only reset path. NVS flash encryption is not enabled by this firmware.
- The optional camera board no longer requires an ignored `secrets.h`; its separate USB serial tool stores Wi-Fi and bearer token in the `bella_cam` NVS namespace. The camera remains opt-in, and its local HTTP bearer-token endpoint must not be exposed over the public Internet.
- Public-mode backend startup and both camera proxy routes fail closed unless the configured camera URL is HTTPS. Plain HTTP is accepted only for private/loopback development hosts.
- Touch telemetry, explicit Touch 4 momentary long-press PTT candidate, bounded recording, microphone RMS/frame counts, I²S drop/DMA diagnostics, and VL53L0X validation/hysteresis are wired into device status. Touch 4 PTT and all servo movement remain disabled by default.
- The Hardware Doctor classifies reported checks as PASS/FAIL/PENDING/UNSUPPORTED, keeps visible pixels and audible sound pending until physically checked, and downloads a sanitized report. Camera capture requires an authenticated explicit button action; no capture or AI request is automatic.
- A WSS URL policy helper rejects HTTP, user-info, alternate paths, query/fragment strings, malformed hosts and invalid ports. This addresses a discovered issue where the firmware checked a legacy macro even after moving credentials to NVS.

## Verification

Commands and offline checks run locally:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests/test_expression_sync.py tests/test_hardware_doctor.py -q
.\scripts\build-firmware.ps1 -Profile diagnostic
.\scripts\build-firmware.ps1 -Profile st7789-240x240
.\scripts\build-firmware.ps1 -Profile ili9341-240x320
.\scripts\build-firmware.ps1 -Profile st7735-128x160
.\scripts\build-firmware.ps1 -Profile touch4-ptt-momentary
.\scripts\build-firmware.ps1 -Profile camera-disabled
.\scripts\build-firmware.ps1 -Profile camera-ai-thinker
```

Results:

| Check/profile | Result |
|---|---|
| Full Python/browser/synthetic-device suite | **100 passed**, 42 dependency/deprecation warnings, 67.57 s; no paid providers called |
| Focused security and Hardware Doctor suite after the transport guard | **13 passed**, 2 warnings, 2.50 s |
| `diagnostic` / `bella_esp32` | **PASS** — RAM 42,700 B (13.0%); app flash 1,058,157 B (33.6%); build 128.96 s |
| `st7789-240x240` | **PASS** — RAM 43,240 B (13.2%); app flash 1,095,309 B (34.8%); build 138.58 s |
| `ili9341-240x320` | **PASS** — RAM 43,344 B (13.2%); app flash 1,096,113 B (34.8%); build 158.73 s |
| `st7735-128x160` | **PASS** — RAM 43,632 B (13.3%); app flash 1,096,101 B (34.8%); build 210.80 s |
| `touch4-ptt-momentary` | **PASS** — RAM 42,716 B (13.0%); app flash 1,059,089 B (33.7%); build 293.95 s |
| `camera-disabled` | **PASS** — RAM 35,844 B (10.9%); app flash 822,593 B (26.1%); build 188.06 s |
| `camera-ai-thinker` | **PASS** — RAM 48,152 B (14.7%); app flash 940,741 B (29.9%); build 227.77 s |
| Flashing / device activation | **NOT RUN** — no device flash; no servo or camera was activated |
| Hardware Doctor camera success/error path | Mocked offline test; not a physical camera capture |
| PowerShell scripts / whitespace | Build, flash and both provisioning scripts parsed; `git diff --check` reported no whitespace error (line-ending conversion notices were emitted) |

The first camera-profile rebuild surfaced a missing cJSON manifest dependency. That was declared in the camera component manifest, and both camera profiles passed on the final source afterward. Firmware build sizes are relative to the target's 3 MiB application partition and 320 KiB RAM target; they do not prove the physical board's flash size or runtime heap headroom.

Build targets inherit PlatformIO `esp32dev`, ESP-IDF 6.0.1, Espressif platform 7.0.1, nominal 4 MiB flash. This is the compiler target, **not confirmation** that the physical board is that module or has that flash size.

## Snapshot gallery

![Embedded idle-eye renderer snapshot](assets/phase2d-face-renderer/idle.png)

More offline expression snapshots: `assets/phase2d-face-renderer/` (happy, love, curious, wink, thinking, error, offline). The snapshots come from host execution of the same pure pixel renderer; they do not exercise SPI, backlight, display color order, or panel offsets.

## Change and safety boundary

All existing Phase 2C edits were preserved. No files were staged or pushed; ignored/untracked build-manager artifacts were left in place. Review `git status` before a later commit. The full GPIO map, friend workflow, physical checklist, Railway release gates and unresolved issues are in the companion documents below.

### Exact working-tree inventory

This is the local handoff inventory, not a commit boundary. It includes pre-existing Phase 2C files that were preserved alongside Phase 2D work. Nothing is staged.

- Backend/device: `app/api/face.py`; `app/core/config.py`; `app/device/face.py`, `http.py`, `registry.py`, `websocket.py`, `doctor.py`.
- Frontend: `app/frontend/app.js`, `face-bridge.js`, `face.html`, `face.js`, `index.html`, `doctor.html`, `doctor.js`, `expression-controller.js`.
- Documentation: `docs/BELLA_FRIEND_HARDWARE_SETUP.md`, `docs/BELLA_PHASE1_FLASHING.md`, `docs/BELLA_PHASE2D_SOFTWARE_COMPLETION.md`, `docs/BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md`, `docs/BELLA_FRIEND_ONE_CLICK_SETUP.md`, `docs/BELLA_PHYSICAL_ACCEPTANCE_CHECKLIST.md`, `docs/BELLA_RAILWAY_RELEASE_CHECKLIST.md`, `docs/BELLA_KNOWN_LIMITATIONS.md`; preserved `docs/BELLA_PHASE2C_EXPRESSION_AUDIO_SYNC.md` and `docs/BELLA_PHASE2C_PROTOCOL.md`.
- Main ESP32 existing files updated: `firmware/bella_esp32/include/bella_audio_i2s.h`, `bella_config.h`, `bella_device_ws.h`, `bella_display.h`, `bella_distance.h`, `bella_face.h`, `bella_runtime.h`; `firmware/bella_esp32/main/CMakeLists.txt`, `idf_component.yml`; `firmware/bella_esp32/platformio.ini`; `firmware/bella_esp32/src/audio_i2s.cpp`, `device_ws.cpp`, `display.cpp`, `distance.cpp`, `main.cpp`, `runtime.cpp`, `touch.cpp`, `wifi.cpp`.
- Main ESP32 new source/config: `firmware/bella_esp32/dependencies.lock`; `firmware/bella_esp32/include/bella_backend_url_policy.h`, `bella_face_renderer.h`, `bella_playback.h`, `bella_provisioning.h`, `bella_tft_profile.h`, `bella_touch_gesture.h`, `secrets.h.example` (now marked deprecated); `firmware/bella_esp32/sdkconfig.bella_esp32`, `sdkconfig.bella_esp32_ili9341_240x320`, `sdkconfig.bella_esp32_st7735_128x160`, `sdkconfig.bella_esp32_st7789_240x240`, `sdkconfig.bella_esp32_touch4_ptt_momentary`; `firmware/bella_esp32/src/provisioning.cpp`.
- Camera board existing files updated: `firmware/bella_esp32_cam/include/cam_config.h`; `firmware/bella_esp32_cam/main/CMakeLists.txt`, `idf_component.yml`; `firmware/bella_esp32_cam/platformio.ini`; `firmware/bella_esp32_cam/src/main.cpp`.
- Camera board new source/config: `firmware/bella_esp32_cam/dependencies.lock`; `firmware/bella_esp32_cam/include/bella_cam_policy.h`, `bella_cam_provisioning.h`, `secrets.h.example` (now marked deprecated); `firmware/bella_esp32_cam/sdkconfig.bella_esp32_cam`, `sdkconfig.bella_esp32_cam_ai_thinker`; `firmware/bella_esp32_cam/src/provisioning.cpp`.
- Operator scripts: `scripts/build-firmware.ps1`, `flash-firmware.ps1`, `provision-device.ps1`, `provision-camera.ps1`.
- Tests: `tests/browser/test_frontend_audio.py`, `tests/test_face_bridge.py`, `tests/test_expression_sync.py`, `tests/test_hardware_doctor.py`, `tests/test_security.py`; native tests `tests/native/test_backend_url_policy.cpp`, `test_camera_provisioning_policy.cpp`, `test_face_playback.cpp`, `test_face_renderer_and_touch.cpp`, `test_servo_safety.cpp`, `render_face_snapshots.cpp`.
- Visual evidence: `docs/assets/phase2d-face-renderer/idle.png`, `happy.png`, `love.png`, `curious.png`, `wink.png`, `thinking.png`, `error.png`, `offline.png`.

PlatformIO-generated `managed_components/` directories and local `.pio` firmware outputs remain in the worktree as build artifacts. Review them separately before any future staging; do not use `git add .`.

### Owner and friend actions

Before sending the package, the owner must review the entire local diff, check only secret presence (do not paste values into chat), configure/review Railway variables and the one-worker/one-replica policy, then deploy through the normal reviewed process. No deployment or provider request was performed here.

The friend’s work is hardware-only: identify exact boards/modules, compare occupied pins and strapping circuitry against the matrix, wire only after power/voltage review, choose the matching build profile, run the confirmation-gated flash/provision scripts, then complete the physical checklist and return the sanitized Doctor report. If a part does not match a supported profile, stop for owner review rather than changing pins or source.

- [Final hardware profile matrix](BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md)
- [Friend setup guide](BELLA_FRIEND_ONE_CLICK_SETUP.md)
- [Physical acceptance checklist](BELLA_PHYSICAL_ACCEPTANCE_CHECKLIST.md)
- [Railway release checklist](BELLA_RAILWAY_RELEASE_CHECKLIST.md)
- [Known limitations](BELLA_KNOWN_LIMITATIONS.md)
