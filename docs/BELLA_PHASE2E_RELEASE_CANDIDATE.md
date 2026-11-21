# Bella Phase 2E — Release Candidate Review

**Review date:** 2026-11-15
**Repository:** `D:\final year project\backend`
**Branch/base:** `main`, local `HEAD` and `origin/main` both `f3fb0e5` at review time
**Decision:** **READY FOR OWNER REVIEW; NOT APPROVED FOR HOSTED OR PHYSICAL RELEASE.**

The local Phase 2C/2D implementation is preserved. No commit, push, Railway change/deploy, paid-provider call, firmware flash, or physical output activation was performed. The current tree is extensive and dirty; the exact proposed source manifest is below. Review it before staging anything.

## Evidence gathered

| Check | Result |
|---|---|
| Full Python, API, browser, and simulated-device suite | **100 passed**, 42 warnings, 67.59 s; no paid provider calls |
| Browser suite, installed Microsoft Edge + generated MP3 + fake providers | **6 passed**, 9 warnings, 43.89 s; validates MediaSource decoding/playback, phrase order, interruption/error handling, and early playback while fake LLM output continues |
| Native controller/firmware policy/snapshot suite | **10 passed**, 4 warnings, 22.09 s; includes native C++ builds/policy tests and renderer snapshots |
| Python compilation | `python -m compileall -q app` passed |
| JavaScript syntax | `node --check` passed for app, face, doctor, bridge, and expression-controller scripts |
| PowerShell scripts | All four scripts parsed; all seven build profiles ran successfully from this path containing spaces |
| Firmware build candidates | **7/7 passed**; see the profile and binary manifest below. No flashing occurred. |
| `git diff --check` | Passed; Git emitted line-ending conversion notices for CRLF/LF, not whitespace errors |
| Local Docker image build | **Not run**: Docker engine is unavailable in this session. Dockerfile/configuration was inspected and its safety assertions pass in tests. |
| Railway hosted configuration/deployment | **Not inspected or changed**; no Railway service access was used |
| Paid APIs / live audio / hardware | **Not run** |

The repeated compiler warning on the main-board TFT builds is `bella_face_renderer.h:59: unused variable 'openness'`. It did not fail any build; it is recorded rather than hidden. Python warnings are dependency/deprecation warnings (AnyIO/pytest, Starlette TestClient/httpx, and Pydantic `datetime.utcnow`).

## TFT renderer visual review

I inspected `docs/assets/phase2d-face-renderer/display-preview.png` and `thinking.png`, plus the individual expression images. The intended iris gradients, pupil/highlight layers, lashes, brows, and distinct eye shapes are present in the generated 240×240 software output. Thinking reads as a half-lidded, upward-gaze expression with the three-dot indicator; the reduced pixel grid necessarily looks less smooth and detailed than the large Face Studio reference. The renderer is centered and legible at its candidate resolution. No clear software-rendering defect justified altering the accepted browser-eye design or making another speculative redesign.

This is host-rendered output from the firmware's pixel renderer. It does **not** verify TFT color order, SPI timing, panel offsets, backlight, physical visibility, or perceived smoothness on the friend's display. Those remain hardware acceptance items. Only the PNG previews are in the proposed source manifest; generated PPM intermediates are excluded.

## Release and security audit

- The Dockerfile uses Python 3.12, installs `ffmpeg`, `git`, and `build-essential`, starts a single Uvicorn worker on `0.0.0.0` using Railway's `PORT` (8000 only as a local fallback), and defaults both Whisper startup preload and interim CPU inference off. Local Compose can override these through its `.env`. Docker healthcheck targets `/health`.
- `/health` is the public liveness check. `/metrics` is behind browser authentication in public mode. Paid HTTP routes, generated audio, and browser voice WebSocket access require the public-mode browser session.
- Public mode fails startup without the minimum browser password, session signing secret, and exact HTTPS origin allowlist. The browser cookie is HttpOnly, Secure in public mode, and SameSite=Strict. Device tokens are separate and firmware receives no provider key.
- `VOICE_DIAGNOSTIC_MODE` and `BOUNDED_FULL_VOICE_TEST` default off and are mutually exclusive. Normal traffic is not latched to a one-turn test. The bounded modes enforce fixed models and provider budgets when deliberately enabled.
- Camera defaults off. Public camera proxy requires HTTPS and a dedicated token; no public direct-to-camera route is approved. Keep camera disabled until its reachable protected transport exists.
- `WHISPER_PRELOAD_ENABLED=false` is honored by the OpenRouter STT adapter: no local model is loaded at startup; the local fallback remains lazy-loaded if needed. `WHISPER_INTERIM_ENABLED=false` avoids interim CPU inference on a small cloud instance.
- The process-local device registry, commands, rate limits, and session state require **one worker and one Railway replica**. This is documented but cannot be enforced or confirmed without Railway access.
- `.env` exists locally, was checked only for presence, and was not read. It is ignored by Git and Docker context. Secret-pattern scanning of candidate application/source/docs found no provider-key pattern. It found certificate private-key filenames only inside downloaded ESP-IDF example components; those trees are now ignored and excluded. No secret values were displayed.
- `firmware/**/managed_components/`, raw PPM snapshots, local `.pio` builds, and the candidate `.bin` files are kept out of the proposed source commit. Existing vendor files were not deleted. Generated firmware binaries are also excluded from Docker build context.
- The firmware provisioning path stores Wi-Fi and device/camera credentials in NVS without flash encryption. The utilities warn about this; disclose it to the friend and do not treat physical storage as secret-safe.

## Hardware and deployment boundary

All seven builds target the configured `esp32dev`/classic ESP32 toolchain profile, nominal 4 MiB flash. Compile success does not identify the real board or display. Keep Servo 1 on GPIO13, Servo 2 on GPIO12 but disabled and strap-gated, GPIO21 reserved, I²S BCLK on GPIO26, and Touch 4 on GPIO27 only after the stated physical rewiring. Do not flash until exact board/flash, every occupied pin, strap pull circuitry, display controller/resolution/offset, power, and sensor variants are confirmed.

No Railway production values were read. Configure the required variable **names** and one-worker/one-replica topology using `BELLA_PHASE2E_OWNER_DEPLOYMENT.md`; never copy local `.env` values into a document or commit. The deployment command, allowlist, login, healthcheck, unauthenticated rejection, and device WSS handshake still need owner-side hosted verification.

## Generated candidate firmware package

These seven files were produced by the passing local builds and copied to `artifacts/phase2e/firmware-candidates/`. A separate archive is available at `artifacts/phase2e/BELLA_PHASE2E_UNTESTED_FIRMWARE_CANDIDATES.zip` (SHA-256 `A30F0214BEE5CC2459312F49D53925E7AF32F66599C8F2F7D735B1A1C8F936D6`). They contain no provisioned Wi-Fi, device, camera, or AI credentials. **Every binary is untested on physical hardware and is not a recommendation to flash it.** Select only after positively identifying the matching hardware; the flash utility still rebuilds and requires explicit confirmation. Candidate binaries and archive are ignored by Git and Docker and are not in the source commit manifest.

| Profile / binary | Bytes | SHA-256 | Physical status |
|---|---:|---|---|
| `diagnostic.bin` | 1,069,024 | `7D5D5D39605F0019F97824D56D2ADA60AA88D7526083D22D2A0DF0AA0ADC3D94` | Not tested |
| `st7789-240x240.bin` | 1,110,096 | `9046ED0F40FD0CAD4B8CBD757FCFAE8C7915D94C9279BB04279BD4CD2F5C18CA` | Not tested; exact panel still needed |
| `ili9341-240x320.bin` | 1,110,880 | `A4C1D48337099E0EFC6C80546725D52690E49EAAEF3539CE55515937CAC7CC09` | Not tested; exact panel still needed |
| `st7735-128x160.bin` | 1,110,896 | `77FA4C047C09FFEA443C0FDD6433512433F5E56B93856AD678D95AEE0776A61E` | Not tested; variant/offset still needed |
| `touch4-ptt-momentary.bin` | 1,070,016 | `615D66E6C3189AB5335715E14B4484C8B83D6C6CCA6EF6263922A4784A2AB8BA` | Not tested; only for confirmed momentary TTP223 |
| `camera-disabled.bin` | 828,528 | `36ABFF71087F44545E6E00F8710F20701591305D8D4DFAE4197CD910E1A6E89B` | Not tested; camera disabled |
| `camera-ai-thinker.bin` | 946,672 | `82D138C92C9C35F934D9FD06C69CA81A5BC3F2BB35DCAB53C88512E642CE6A24` | Not tested; AI-Thinker mapping only |

## Proposed source commit manifest

This is the exact reviewed candidate path list as of this report, including the pre-existing Phase 2C/2D changes preserved in the tree and the Phase 2E documents. It is **not staged** and is not authorization to commit. Do not use `git add .`. `.env`, PPM intermediates, `.pio`, managed components, and candidate binaries are excluded.

```text
.dockerignore
.gitignore
Dockerfile
app/api/face.py
app/core/config.py
app/device/doctor.py
app/device/face.py
app/device/http.py
app/device/registry.py
app/device/websocket.py
app/frontend/app.js
app/frontend/doctor.html
app/frontend/doctor.js
app/frontend/expression-controller.js
app/frontend/face-bridge.js
app/frontend/face.html
app/frontend/face.js
app/frontend/index.html
docs/BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md
docs/BELLA_FRIEND_HARDWARE_SETUP.md
docs/BELLA_FRIEND_ONE_CLICK_SETUP.md
docs/BELLA_KNOWN_LIMITATIONS.md
docs/BELLA_PHASE1_FLASHING.md
docs/BELLA_PHASE2C_EXPRESSION_AUDIO_SYNC.md
docs/BELLA_PHASE2C_PROTOCOL.md
docs/BELLA_PHASE2D_SOFTWARE_COMPLETION.md
docs/BELLA_PHASE2E_FINAL_ACCEPTANCE_MATRIX.md
docs/BELLA_PHASE2E_FRIEND_HANDOFF.md
docs/BELLA_PHASE2E_OWNER_DEPLOYMENT.md
docs/BELLA_PHASE2E_RELEASE_CANDIDATE.md
docs/BELLA_PHYSICAL_ACCEPTANCE_CHECKLIST.md
docs/BELLA_RAILWAY_RELEASE_CHECKLIST.md
docs/assets/phase2d-face-renderer/angry.png
docs/assets/phase2d-face-renderer/curious.png
docs/assets/phase2d-face-renderer/display-preview.png
docs/assets/phase2d-face-renderer/error.png
docs/assets/phase2d-face-renderer/excited.png
docs/assets/phase2d-face-renderer/happy.png
docs/assets/phase2d-face-renderer/idle.png
docs/assets/phase2d-face-renderer/listening.png
docs/assets/phase2d-face-renderer/love.png
docs/assets/phase2d-face-renderer/offline.png
docs/assets/phase2d-face-renderer/sad.png
docs/assets/phase2d-face-renderer/sleepy.png
docs/assets/phase2d-face-renderer/speaking.png
docs/assets/phase2d-face-renderer/surprised.png
docs/assets/phase2d-face-renderer/thinking.png
docs/assets/phase2d-face-renderer/wink.png
firmware/bella_esp32/dependencies.lock
firmware/bella_esp32/include/bella_audio_i2s.h
firmware/bella_esp32/include/bella_backend_url_policy.h
firmware/bella_esp32/include/bella_config.h
firmware/bella_esp32/include/bella_device_ws.h
firmware/bella_esp32/include/bella_display.h
firmware/bella_esp32/include/bella_distance.h
firmware/bella_esp32/include/bella_face.h
firmware/bella_esp32/include/bella_face_renderer.h
firmware/bella_esp32/include/bella_playback.h
firmware/bella_esp32/include/bella_provisioning.h
firmware/bella_esp32/include/bella_runtime.h
firmware/bella_esp32/include/bella_tft_profile.h
firmware/bella_esp32/include/bella_touch_gesture.h
firmware/bella_esp32/include/secrets.h.example
firmware/bella_esp32/main/CMakeLists.txt
firmware/bella_esp32/main/idf_component.yml
firmware/bella_esp32/platformio.ini
firmware/bella_esp32/sdkconfig.bella_esp32
firmware/bella_esp32/sdkconfig.bella_esp32_ili9341_240x320
firmware/bella_esp32/sdkconfig.bella_esp32_st7735_128x160
firmware/bella_esp32/sdkconfig.bella_esp32_st7789_240x240
firmware/bella_esp32/sdkconfig.bella_esp32_touch4_ptt_momentary
firmware/bella_esp32/src/audio_i2s.cpp
firmware/bella_esp32/src/device_ws.cpp
firmware/bella_esp32/src/display.cpp
firmware/bella_esp32/src/distance.cpp
firmware/bella_esp32/src/main.cpp
firmware/bella_esp32/src/provisioning.cpp
firmware/bella_esp32/src/runtime.cpp
firmware/bella_esp32/src/touch.cpp
firmware/bella_esp32/src/wifi.cpp
firmware/bella_esp32_cam/dependencies.lock
firmware/bella_esp32_cam/include/bella_cam_policy.h
firmware/bella_esp32_cam/include/bella_cam_provisioning.h
firmware/bella_esp32_cam/include/cam_config.h
firmware/bella_esp32_cam/include/secrets.h.example
firmware/bella_esp32_cam/main/CMakeLists.txt
firmware/bella_esp32_cam/main/idf_component.yml
firmware/bella_esp32_cam/platformio.ini
firmware/bella_esp32_cam/sdkconfig.bella_esp32_cam
firmware/bella_esp32_cam/sdkconfig.bella_esp32_cam_ai_thinker
firmware/bella_esp32_cam/src/main.cpp
firmware/bella_esp32_cam/src/provisioning.cpp
scripts/build-firmware.ps1
scripts/flash-firmware.ps1
scripts/provision-camera.ps1
scripts/provision-device.ps1
tests/browser/test_frontend_audio.py
tests/native/render_face_snapshots.cpp
tests/native/test_backend_url_policy.cpp
tests/native/test_camera_provisioning_policy.cpp
tests/native/test_face_playback.cpp
tests/native/test_face_renderer_and_touch.cpp
tests/native/test_servo_safety.cpp
tests/test_expression_sync.py
tests/test_face_bridge.py
tests/test_hardware_doctor.py
tests/test_security.py
```

This source inventory is for review only. If anything in it is not intended for the next commit, remove that path from a future explicit staging list; do not delete it from disk. The repository status should be checked again immediately before any owner-authorized commit.

## Final gate

- **Core software issue known to block the simulated/browser/device protocol:** none found by this offline pass.
- **Owner deployment gate:** pending Docker image build on an available engine and owner verification of Railway variables, resource plan, one worker/replica, and hosted auth/device behavior.
- **Friend handoff:** can begin with board/photo/model-number identification and the checklist; do not flash or wire from profile names alone.
- **Physical release:** blocked pending board/flash/TFT/sensor identification, GPIO/strap/power audit, and visible/audible acceptance evidence.
- **Stop boundary honored:** no Git write, Railway mutation/deploy, paid provider call, or flash.
