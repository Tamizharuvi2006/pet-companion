# Bella Phase 1G — Full-Voice Acceptance Readiness

**Date:** 2026-11-15
**Project:** `D:\final year project\backend`
**Result:** Offline and local-server preflight passed. Stopped before any paid voice turn.

## Scope and outcome

This phase removes accidental pet-voice activity from the bounded one-shot test, confirms the full-voice budget and playback behavior offline, and prepares the local browser/server for a separately authorized live turn. No OpenRouter STT, chat, or Kokoro request was made; no Edge TTS request, deployment, Git push, GPIO change, or firmware flash was made.

The published 1.2-second pet-TTS preloader was already absent from the current local frontend. A second guard is now in place: the browser reads the authenticated, read-only `/client-config` response and synthesizes pet speech only when `pet_voice_synthesis_enabled` is true. That value is false for either voice-test mode. Configuration errors fail closed. Normal-mode pet speech remains click-triggered.

## Offline verification

- **75 Python tests passed** (`python -m pytest -q`), including the existing bounded-provider, one-shot-latch, full-reply coverage, generated-MP3 browser playback, cancellation, and auth tests.
- New Microsoft Edge browser checks passed in bounded and normal modes: loading the page for longer than the former preload delay made zero paid-route POSTs and did not claim the latch; clicking a pet made zero TTS POSTs in bounded mode, while normal mode issued only the locally intercepted fake `/tts` request.
- The full-voice tests verified that text is spoken once and in order across no more than three segments, that GPT can continue after the first audio segment is yielded, and that oversized or failed audio is reported as incomplete instead of silently claiming complete coverage. The local per-input cap remains 2,000 characters.
- `python -m compileall -q app tests` passed.
- `node --check app/frontend/app.js` passed.
- `git diff --check` passed; Git printed line-ending conversion warnings for existing modified files.

The browser tests use fake/intercepted providers and local fixtures. They are not live provider or human-audibility results.

## Bounded mode and limits

The running process uses temporary process-local overrides; `.env` was not changed:

```text
VOICE_DIAGNOSTIC_MODE=false
BOUNDED_FULL_VOICE_TEST=true
WHISPER_INTERIM_ENABLED=false
TTS_RACE_ENABLED=false
TTS_PROVIDER=kokoro
MODEL_NAME=openai/gpt-4o-mini
OPENROUTER_STT_MODEL=openai/whisper-large-v3-turbo
OPENROUTER_TTS_MODEL=hexgrad/kokoro-82m
OPENROUTER_TTS_VOICE=af_bella
TTS_FIRST_CHUNK_WORDS=6
```

At the application dispatch boundaries, bounded mode allows at most **1 OpenRouter STT, 1 OpenRouter chat, 3 Kokoro TTS, and 0 Edge TTS attempts**. The one-shot latch is claimed by the first protected voice operation, not by page/static-file loads or `/client-config`. Provider limits and disabled retry/race behavior are exercised by the offline suite. A new server process creates a fresh latch; an actual microphone/text voice turn would consume it.

## Local server preflight

Port 8000 was free when checked, so there was no old process to stop. Bella was started as a single Uvicorn worker with no reload:

```text
PID 2260 — http://127.0.0.1:8000
```

Verified after startup:

- `GET /health`: HTTP 200, status `ok`.
- `GET /`: HTTP 200.
- `GET /client-config`: HTTP 200, `pet_voice_synthesis_enabled=false`.
- `GET /auth/session`: HTTP 200 in local development mode; authentication is intentionally not required in this environment.
- Served `/app.js` SHA-256 matched `app/frontend/app.js` exactly.
- Startup logged `mode=bounded_full_voice_test` and `provider_limits=stt:1,chat:1,kokoro:3,edge:0`.
- Startup made no OpenRouter or Edge provider request. It did perform a Hugging Face model metadata GET while loading the local Faster-Whisper fallback; this is not a paid voice-provider request.
- No `voice_diagnostic_session_claimed` event appeared, and subsequent checks were limited to health/config/session/static GETs. The pet UI is disabled for TTS in this mode.

Public-mode authentication is covered by the offline security suite: unauthenticated `/client-config` is rejected, login/session handling succeeds, and the configuration endpoint remains behind `browser_principal`. The live server itself is in development mode, so its `auth_required=false` response is expected and is not a production-auth acceptance result.

## Live acceptance status and remaining gate

**Not performed:** microphone recording, paid STT/chat/TTS calls, actual browser audio decoding from Kokoro, audible playback confirmation, human speech-quality assessment, end-to-end latency, or real-provider cost measurement. No live metrics are claimed.

The process is ready at `http://localhost:8000`. Stop here before pressing the microphone, sending a chat message, or calling a protected voice endpoint; any such voice operation can consume the single-use test session. A separate explicit authorization is required before making the one bounded paid voice turn. After that turn, record server and browser trace timings plus human playback observations; do not infer audibility from server-side `speech_coverage` alone.
