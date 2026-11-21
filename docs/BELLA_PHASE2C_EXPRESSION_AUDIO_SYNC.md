# Bella Phase 2C — Expression and audio synchronization

Date: 2026-11-15. Software implementation and offline validation; no paid calls, .env edits, live voice test, Git push, deployment, firmware flash or Uvicorn restart.

## Implemented

- Shared browser expression controller with versioned, text-free events, source priorities, expiry, retired-turn and duplicate-sequence protection. Simulation and browser voice use this controller; existing layered anime rendering is preserved.
- Browser listening follows recording, thinking follows stop, speaking follows HTML media `playing`, buffering follows `waiting`, idle follows `ended`, and recoverable failures clear voice activity before a short error. New turns dispose old playback; socket disconnect pauses audio and emits offline.
- Same-origin Face Studio **Browser Voice** mode receives the browser adapter events via BroadcastChannel. **Connected Device** mode remains separate, displays device face/conversation, server audio completion, reported audio status, basis/estimate flags, turn/sequence, touch, command status and safe errors. No browser event claims hardware output.
- Backend distinguishes server audio completion from device playback evidence. It no longer labels output as speaking merely because PCM was sent, nor forces idle at server-generation completion. Playback reports require the current authenticated turn, valid evidence and increasing sequence; timeout/cancel/disconnect are not delivery success.
- ESP32 final-turn queue marker, generation-tagged cancellation, TX DMA callback fence and estimated playback reports. Server turn_complete is no longer used as speaker-drain proof. I²S write timeout argument is milliseconds, matching the installed API.
- ESP32 face task is nonblocking with respect to network reporting. The separate bounded control sender discards stale connection epochs. Offline touch temporarily animates while geometry retains an offline indicator. Errors recover after 2.2 seconds; active voice status outranks temporary touch/preview emotion.
- Driver-independent normalized geometry exposes eye openness, width, left/right openness, curve/angle, iris gaze, pupil size, color warmth, crossed-pupil flag and offline indicator through a synchronized snapshot. No unverified TFT driver is enabled.
- Device preview commands carry a connection/session identity and increasing sequence. Existing authentication, pinned models, source GPIOs, servo gates, single-worker Docker startup and one-shot browser voice safeguards remain intact.

## Tests and build

**Final Python suite: 94 passed, 42 deprecation warnings, 52.92 seconds.** All 85 baseline tests remain included. Python compilation and JavaScript syntax checks for the controller, voice client, face renderer and dashboard passed. `git diff --check` passed with existing LF/CRLF conversion warnings. Tests use fake providers, generated MP3/synthetic PCM, simulated device reports, a real headless Edge browser, and host-native C++ model execution. These are not live-provider, acoustic or physical TFT tests.

**ESP32 firmware build succeeded** with the existing `espressif32@7.0.1` / installed ESP-IDF 6.0.1 toolchain using a temporary whitespace-free R: alias. Build compilation caught and corrected the callback's mutable `i2s_event_data_t*` signature. Final incremental build after stale-message guards: **12.28 seconds**, static RAM **18,912/327,680 bytes**, flash **266,505/3,145,728 bytes**. The temporary alias is removed after validation; source files were not moved. No flash occurred.

The native C++ test compiles the actual face/fence headers using WSL g++ in this environment. It covers four pads, debounce, expiry, conversation priority, offline touch plus offline flag, blink/geometry bounds, fence progression, cancellation generation and uint32 wrap. The model test does not execute the ESP32 DMA peripheral.

Browser integration opens a second Face Studio tab under the same origin and exercises fake microphone → generated audio → media playback, injected browser error and interrupted/new turn. It checks ordered listening/thinking/speaking events, browser-only destination, no private text, and return to idle. Registry tests cover server-send versus drain distinction, stale/duplicate events, cancel, reconnect and acknowledgment timeout. Fake authenticated WebSocket testing sends synthetic PCM through a complete fake-provider turn and then separate simulated playback acknowledgments.

## Reuse and changed areas

Reuses `/ws/chat`, `/ws/device`, PCM framing, streaming turn service, browser media playback, signed cookies/origin controls, per-device authentication, registry and firmware Wi-Fi/TLS handling. New files: `app/frontend/expression-controller.js`, `firmware/bella_esp32/include/bella_playback.h`, `tests/test_expression_sync.py`, `tests/native/test_face_playback.cpp`, and Phase 2C docs. Updated existing frontend adapter, face panel, device contract/registry/router, firmware audio/display/runtime/device control and browser integration tests.

See `BELLA_PHASE2C_PROTOCOL.md` for exact event fields and evidence limits. See `BELLA_RAILWAY_DEPLOYMENT.md` for deployment preparation. Registry, queues and latch remain process-local: **one worker and one replica**. No hosted URL, Railway deployment or physical device connection is verified by this work.

## Developer and friend steps

The existing server was intentionally not restarted. To load new Python code and frontend script references coherently, schedule a fresh single-worker process when ready; that creates a new bounded-test latch. Do not consume it by running a voice turn without separate paid authorization.

For offline checks:

```powershell
Set-Location 'D:\final year project\backend'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app tests
node --check app\frontend\expression-controller.js
node --check app\frontend\app.js
node --check app\frontend\face.js
node --check app\frontend\face-bridge.js
```

After an intentional start, open `/` and `/face.html` using exactly the same hostname/profile, choose Browser Voice mode in Face Studio. Simulation needs no device or provider. Actual voice still requires its separate authorization. Friend must confirm exact TFT controller/resolution/rotation and ESP32 board/flash before any physical rendering driver or flash. Keep GPIO12 servo safety gates off and GPIO21 reserved.

## Physical acceptance still pending

No acoustic output was heard or measured here. `i2s_write_accepted` and `dma_ring_fence` are estimated device evidence, not exact acoustic timestamps. Real DMA scheduling, shared-clock effects during TX reset, queue saturation, Wi-Fi failures, local touch response, amplifier output and visible TFT frames require the friend's physical tests. The generic geometry is not a pixel-perfect ESP32 reproduction of the browser's layered eye artwork. No full-frame video is streamed.
