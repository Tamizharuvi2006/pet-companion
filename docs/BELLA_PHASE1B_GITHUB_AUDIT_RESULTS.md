# BELLA Phase 1B — GitHub Audit Results

Date: 2026-11-15
Project: `D:\final year project\backend`
Status: Offline security and browser-playback work completed; live-provider acceptance is waiting for explicit authorization.

## Checkout and scope

- Local `HEAD` and `origin/main` both resolved to `3ee383bb0be08291414875c77ea4684a9cb4ea77`; no branch divergence was found. The public repository's README still described the old “first completed audio” race, which has now been corrected locally. [GitHub repository](https://github.com/Tamizharuvi2006/pet-companion)
- The existing untracked `docs/BELLA_PHASE1B_LIVE_ACCEPTANCE.md` was present before this audit and was left untouched.
- No provider credentials were printed or changed. No paid provider request, deployment, credential rotation, or hardware flash was performed.

## Fixes made

### Browser and provider security

- Added shared-password browser login at `/auth/login`, status at `/auth/session`, and logout at `/auth/logout`. Public mode uses an HttpOnly, Secure, SameSite=Strict, HMAC-signed session cookie. This is a stateless shared-password session, not per-person accounts; logout clears the browser cookie, while a copied cookie remains valid until its expiry.
- Public/staging startup now fails closed unless the access password, 32+ character signing secret, and exact HTTPS origin allowlist are configured. Local development remains login-free.
- `/chat`, `/stt`, `/tts`, `/talk`, `/metrics`, generated `/audio/*`, and `/ws/chat` are protected in public mode. HTTP mutation origins and WebSocket origins are checked against the allowlist.
- Added per-session request limits, bounded limiter key storage, active browser/recording/voice-turn capacity gates, and a shared in-process semaphore for provider calls.
- WebSocket validation rejects malformed base64, oversized encoded/raw frames, cumulative recordings above the configured byte cap, and server-measured recordings beyond the time cap. Client-reported duration is not trusted. Disconnects cancel interim work, clear recording buffers, remove temporary files, and release capacity.
- Added a 128-character WebSocket session-ID schema bound. Request text also has Pydantic limits.
- Pet-click speech no longer pre-generates a second, unrequested line; each click requests only its selected phrase.

Default limits and deployment variables are documented in `.env.example`. Rate limits, session counts, and concurrency are process-local. Multi-replica Railway deployments need shared rate/capacity controls (for example Redis or an edge gateway) before relying on them as global quotas.

### TTS stream and browser playback

- Kokoro/Edge streaming race now selects only after a bounded probe finds two consecutive complete MP3 frames. This is MPEG framing validation, **not** proof that the bytes decode or sound correct. The loser task/stream is cancelled and closed.
- A failure after selected audio has started emits an abort; the browser clears the failed turn and offers a user-triggered full-response retry. It does not silently switch providers mid-phrase, which could splice or repeat speech and spend again.
- MediaSource retains ordered MP3 appends, caps pending data at 4 MiB, handles source/append/abort/close errors, cancels previous-turn media, revokes object URLs, and keeps the complete-file playback path when progressive MP3 MediaSource is unsupported.
- Added browser `waiting` timing events to expose post-start audio starvation.
- Later TTS phrases remain sequential. No real provider trace demonstrated that synthesis gaps, rather than phrase generation/provider latency, justify additional paid concurrency. No concurrency change was made.

## Validation

| Check | Result |
| --- | --- |
| Python test suite | `35 passed, 6 non-blocking dependency deprecation warnings` |
| Python/JavaScript checks | `compileall` and `node --check app/frontend/app.js` passed |
| Whitespace check | `git diff --check` passed (Git printed line-ending normalization notices only) |
| Local app | `http://127.0.0.1:8000/health` returned `ok`; `/` and `/app.js` returned 200; Edge refreshed and showed `Ready` |
| Browser MP3 acceptance | Real installed Microsoft Edge, local generated MP3 tones, actual Bella frontend/WebSocket, fake in-process AI/STT/TTS; no provider calls |
| ESP32 builds | Both `bella_esp32` and `bella_esp32_cam` PlatformIO builds succeeded; no flashing or pin changes |
| Paid-provider playback | Not run; authorization gate preserved |

### Generated-audio browser results

The headless Edge test generated three valid 1.25-second MP3 sine tones with FFmpeg, streamed them as three ordered TTS phrases through the actual browser frontend and WebSocket handler, and exercised real `audio/mpeg` MediaSource decoding/playback. The fake LLM intentionally continued after its first phrase. The test observed all three stream starts/ends, a browser `playing` event before the first phrase stream ended, playback before the full reply, playback completion, and no post-start `waiting` event or media error.

Browser-local monotonic measurements from one synthetic run (not production/provider latency):

| Interval | Measured |
| --- | ---: |
| First text delta → first MP3 bytes received | 3 ms |
| First text delta → browser playback start | 111 ms |
| Playback started → first TTS phrase stream ended | 1,100 ms |
| Playback started → full reply received | 3,322 ms |
| First text delta → full synthetic playback complete | 3,993 ms |

These measurements prove the browser can decode and start the generated stream before TTS and LLM completion. They do **not** establish human-perceived speech latency, spoken-word continuity, voice quality, real Kokoro/Edge incremental behavior, or physical-speaker playback. No timestamps were subtracted across the browser/server clocks.

## Live test readiness and cost gate

Presence-only runtime inspection showed local development mode, `TTS_PROVIDER=kokoro`, the Kokoro/Edge race enabled, `TTS_FIRST_CHUNK_WORDS=6`, and final STT configured as `openai/whisper-large-v3-turbo`. Secret values were not read out or printed.

For one controlled, one-phrase live voice turn, expect **3 OpenRouter requests** (one Whisper STT, one GPT chat stream, and one Kokoro TTS race request), plus **one Edge TTS request** in the race. If the reply is split into `N` phrases, expect one STT + one chat + `N` Kokoro calls, plus `N` Edge calls while racing. A cancelled race loser may already have consumed provider resources. No live request was issued. The first paid test still needs explicit authorization; after that single case, stop and review its trace before any further comparisons.

## Hardware and remaining issues

- Firmware, protocol, authentication, and wiring were not changed. Proposed allocation remains Servo 1 GPIO13; Servo 2 GPIO12 (safety-gated); GPIO21 reserved; shared I²S BCLK GPIO26; I²S WS GPIO25; Touch 4 GPIO27 after rewiring.
- PlatformIO created local `managed_components/`, `dependencies.lock`, and environment-specific `sdkconfig.*` outputs during those builds. They remain untracked and unstaged; review before adding them to a commit. The component/config outputs can be regenerated, though dependencies may need to be downloaded again if removed.
- No board was flashed or physically exercised. GPIO12 strapping/pull-up/startup safety still requires exact board identification and physical verification.
- Real-provider response streaming (whether Kokoro sends playable MP3 progressively or in a near-complete burst), actual provider fallback timing, real speech continuity, voice quality, and physical ESP32 speaker latency remain unverified.
- Current limiter and concurrency state is per process, and sessions are stateless signed cookies. Use shared state and a revocable session store if global quotas or immediate session revocation become requirements.

## First authorized live browser case

Keep `TTS_FIRST_CHUNK_WORDS=6`. Start the local app, use one short voice prompt in Edge, and capture the existing trace stages for STT completion, first LLM delta, phrase ready, provider valid prefix, browser first bytes, browser `playing`, and completion. Inspect the trace and listen for missing/repeated words, stalls, clipping, and natural phrase joins. Do not run the 4/6/8 comparison set until the single baseline has been reviewed and separately authorized.
