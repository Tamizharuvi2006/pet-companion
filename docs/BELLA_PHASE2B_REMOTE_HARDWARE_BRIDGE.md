# Bella Phase 2B — Remote bridge implementation

Date: 2026-11-15. Offline software work only. No paid APIs, push, deployment, live-session consumption or flash.

```text
Face Studio simulation → local animation (no network)
Authenticated Face Studio → face-only HTTP command → one-slot registry queue
ESP32 → outbound authenticated WSS /ws/device → 10 s ping/pong
                  ← queued compact face_command on next ping
ESP32 local face engine → face_ack + sequenced face_report → registry
Authenticated Face Studio ← 3 s status polling ← registry
TTP223 → local debounced face event → optional face_report
Existing ESP32 voice lifecycle → local conversation-priority face state
```

## Reuse and new code

Reuses device token checks, signed browser sessions/origin checks, `/ws/device`, audio protocol v1, registry, rate limiter, existing firmware Wi-Fi/TLS/WebSocket code and anime renderer. New `app/device/face.py` contract, `app/api/face.py` face-only API, `face-bridge.js` panel, registry queue/report metadata and tests. Firmware `display.cpp` now owns a persistent generic animation task and latest-event queue; touch no longer updates a discarded model or calls voice/movement actions. Existing GPIO definitions and servo guards remain.

## Contract and acknowledgement

Expressions: idle, happy, love, excited, curious, surprised, sad, angry, sleepy, wink, listening, thinking, speaking, offline, error. Face protocol version 1 extends, rather than replaces, control protocol version 1.

`face_command`: version, face_version, command_id (UUID hex), expression, duration_ms (250–5000), priority 10, return_to_idle true. Duration defaults to 1800 ms. The server waits for the next device ping to dispatch (up to about ten seconds); this is a safe bounded diagnostic bridge, not frame streaming. Queue is latest-event-only per connected device; commands expire after 15 seconds. There is no automatic retry. A timed-out unacknowledged command is shown as such, not delivered.

`face_ack`: version, face_version, command_id. It means accepted into the device engine queue, **not TFT drawn or audio played**. Only the current pending command can be acknowledged. Firmware suppresses an immediate duplicate command ID. No replay across reconnect is attempted; pending commands are discarded on disconnect.

`face_report`: version, face_version, sequence (uint32), expression, optional touch_pad 1–4. Sequence increases for this device boot; the server rejects stale/duplicate reports per authenticated connection. Reports run at about two-second intervals and immediately for accepted touch events. Wall-clock heartbeat strings are for diagnostics, not cross-device latency calculation. No rendered frames are transmitted.

API: `GET /api/face/devices`; `POST /api/face/{device_id}/expression` accepts only expression/duration, never GPIO, audio or arbitrary commands. Unknown fields/expressions are rejected. Commands require configured device identity and face capability. Browser rate is 30 commands/minute/principal; report rate 120/minute/device. Device control messages retain the 4096-byte cap, hello authentication deadline and receive timeout.

## Security and ownership

This is a **single shared owner** application: the browser password/session authorizes access to all provisioned IDs in `BELLA_DEVICE_TOKENS`, not an arbitrary supplied identity. Unprovisioned records are filtered out of dashboard results. There is no multi-user tenant/pairing system; do not expose this as a multi-tenant service. Browser mutations enforce allowed Origin and sessions in production; device tokens never go into client config or the panel. The device's WSS certificate bundle remains enabled; insecure WS is refused unless explicitly opting into local development firmware. Docker excludes firmware and secrets.

## Face and voice boundary

The layered anime design is preserved. Simulation has no face API requests; connected mode explicitly polls authenticated reports and gives no physical-delivery claim. Status/pad data is inserted as text, not HTML. Connection errors become offline; switching modes invalidates outstanding polling responses. Existing browser login can be reused; the face panel also has a password login form when required.

Firmware status precedence: conversation/network/error state over temporary emotion, then idle. Its single owner task interpolates geometry without allocations in the animation model; bounded touch events are debounced/rising-edge driven and coalesced. Local animation does not wait for network commands. Network reporting currently shares that task and can wait on the existing send mutex; render-loop latency under a saturated socket still needs improvement/measurement. Offline has priority over temporary emotion, so touch acceptance while disconnected does not currently replace the offline face.

Existing device voice lifecycle is reused as reported (listening, processing→thinking, speaking, idle). **The existing firmware treats server turn_complete as completion, which is not guaranteed to mean the speaker DMA has finished.** This phase does not invent an audible completion signal. Exact speech-synchronized idle needs a tested device drain/completion protocol before claiming physical voice-state acceptance. The independent browser voice chat is not yet forwarded to the hardware face as an authoritative playback state.

## Validation and limitations

Final full regression: **85 passed**, including nine focused bridge tests and the real headless Edge face-panel test with fake presence/command responses. Python compilation, syntax checks for both face JavaScript files and `git diff --check` passed (existing LF/CRLF warnings only).

Firmware build: `pio run -d R:\firmware\bella_esp32` succeeded after aliasing the existing checkout with `subst R:` to avoid ESP-IDF's whitespace-path restriction. Initial full build took 179.42 seconds; the final incremental build after touch cleanup succeeded in 8.79 seconds. Reported static RAM 18,816/327,680 bytes; flash 251,713/3,145,728 bytes. ELF symbol inspection confirmed `app_main`, `bella_display_init` and `bella_ws_init` were linked. Build success is not physical validation. The temporary drive alias was removed after the build; no source files were moved.

Browser test verifies simulation has zero API/provider posts, expression/touch controls animate, connected mode displays a mock device and submits only a face command, and no JavaScript exception occurs. It does not establish artistic approval, physical rendering or network hardware acceptance.

This is a tested bridge foundation, **not full Phase 2B completion** while the following remain: authoritative browser-voice→device lifecycle synchronization, real speaker-drain completion semantics, complete automated firmware priority/touch parity tests, independent network-report task/backpressure, and confirmed TFT rendering backend. Hardware availability is not blocking further software work; these are explicitly pending software acceptance items. Physical wiring, flashed boot, display output and speaker quality also remain unverified.

Deployment and handoff procedures: `BELLA_RAILWAY_DEPLOYMENT.md` and `BELLA_FRIEND_HARDWARE_SETUP.md`. Do not restart the current Phase 1G bounded voice process simply to preview new Python routes; schedule that restart separately. No public Railway URL is claimed.
