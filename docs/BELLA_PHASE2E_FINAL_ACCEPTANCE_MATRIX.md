# Bella Phase 2E — Final Acceptance Matrix

**Review date:** 2026-11-15. A pass below is scoped to the evidence named; it is not a general physical/hosted acceptance claim.

| Area | Offline/software evidence | Physical/hosted evidence | State |
|---|---|---|---|
| Browser chat and expressions | Full tests; browser integration with real Edge MediaSource and local generated MP3 passed | Owner's live microphone/provider voice acceptance not rerun here | **Offline pass; live pending** |
| Browser audio streaming | 6 browser tests pass, including ordered generated MP3, early playback before fake LLM completion, browser error and new-turn cancellation | No live Kokoro/Edge audio playback or manual listening in this audit | **Offline pass; live pending** |
| Authentication and origin security | Production-mode tests cover missing config, exact HTTPS origins, login, hardened cookie, protected routes and WebSocket | Actual Railway variables/domain/login not accessible | **Offline pass; hosted pending** |
| Health and metrics | `/health` and `/metrics` routes and security behavior covered by tests | Railway healthcheck and authenticated hosted metrics not checked | **Offline pass; hosted pending** |
| Simulated cloud/device protocol | Full test suite and native protocol/face/policy tests pass; auth, heartbeat, events, audio framing, cancellation and sanitized Doctor covered offline | No ESP32 connected; no hosted WSS handshake | **Offline pass; device pending** |
| Main ESP32 candidates | `diagnostic`, ST7789, ILI9341, ST7735 and Touch 4 momentary builds pass | Board/module, flash, display, GPIO voltage and panel still unidentified | **Build pass; flash blocked** |
| Camera candidates | Camera-disabled and AI-Thinker profiles pass; camera route requires approved transport | Exact camera/sensor and public/private network route unknown; camera must stay off | **Build pass; activation blocked** |
| TFT face renderer | 240×240 snapshots visually inspected; renderer output is readable and expressions distinguishable in software | SPI/panel/controller/color order/offset/backlight and visible pixels untested | **Software pass; display pending** |
| GPIO/wiring safety | Firmware preserves Servo1=13, Servo2=12 gated off, GPIO21 reserved, I²S BCLK=26, Touch4=27 after rewire | External strap pulls, board flash voltage, all physical wiring not audited | **Map preserved; physical audit pending** |
| Touch/proximity | Native/model tests and simulated sensor/gesture paths pass | TTP223 mode/polarity, VL53L0X orientation/range not checked | **Offline pass; physical pending** |
| Servo safety | Compiles disabled by default; compile-time guard blocks GPIO12 enable without strap confirmation | Servo model, supply, mechanics, travel and strap levels unknown | **Disabled; activation blocked** |
| Railway Docker image | Dockerfile, ignore rules, command, and healthcheck statically inspected; tests assert one worker, host, port and production mode | Local Docker engine unavailable; image build and Railway service config unverified | **Configuration reviewed; image/host pending** |
| Package hygiene | `.env` presence-only checked and ignored; generated components, PPMs, bins excluded from source manifest; no candidate secret values emitted | Owner must re-check before staging/push | **Offline review pass; owner gate pending** |

## Acceptance decision

- Core software and simulated flows: **offline accepted for owner review**.
- Source release candidate: **not staged, committed, pushed, or deployed**.
- Railway release: **pending Docker image build and owner-side configuration/hosted checks**.
- Hardware handoff: **identification can begin now; flashing and activation cannot**.
- Core robot physical acceptance: **pending** exact board and module identification, safe GPIO/strap/power review, visible display output, actual mic/speaker playback, touch and distance tests.
- No live provider request, firmware flash, camera capture, or servo activation occurred.

## Exit criteria for the remaining gates

1. Owner reviews the exact source manifest and explicitly authorizes any commit/push/deploy.
2. Docker image builds locally or in the reviewed Railway pipeline; health and public-auth settings pass without a paid AI call.
3. Owner verifies one worker/replica, resource headroom, variables by name, and secure origin/device auth in Railway.
4. Friend supplies exact board/module IDs and wiring photos; unsupported parts stop for review.
5. Matching firmware profile is flashed only after the GPIO/strap/power checklist; physical TFT, mic, speaker, touch and distance evidence is recorded.
6. Camera and servo acceptance remain separate opt-in gates; neither is inferred from the core robot tests.
