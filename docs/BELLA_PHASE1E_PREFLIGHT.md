# Bella Phase 1E — Single-Run Live Acceptance Preflight

**Status:** Preflight passed. The user subsequently ran the one-shot microphone turn in Edge; this report records that already-completed run. No additional provider request was initiated by Codex. The diagnostic session is now consumed.

## Server and browser readiness

- The previously verified Bella Uvicorn listener on port 8000 was restarted from this checkout as a single worker, without `--reload`.
- New process PID: `6456`; `/health` returned `{"status":"ok","service":"Bella AI Cloud","environment":"development"}`.
- Process-local diagnostic settings were applied without editing `.env`: diagnostic mode on, interim Whisper off, Kokoro selected, TTS race off.
- Startup logged the approved settings: GPT `openai/gpt-4o-mini`; STT `openai/whisper-large-v3-turbo`; TTS `hexgrad/kokoro-82m`, voice `af_bella`; interim and race both false; limits STT 1 / chat 1 / Kokoro 1 / Edge 0. Credential presence was checked without displaying the credential.
- `GET /`, `GET /app.js?v=phase1e`, and `/auth/session` returned successfully. `index.html` now references versioned CSS/JS assets so the previous unversioned JavaScript cache key is not reused.
- Edge displayed the updated page at `http://localhost:8000/?phase1e=ready`, including the diagnostic notice. The notice states that only the first phrase will be spoken.

## One-shot lock and offline verification

`DiagnosticSessionLatch` is initialized once at app startup. Its shared async lock arbitrates HTTP and WebSocket attempts; the first eligible paid-route request or first valid audio frame consumes the session. Errors, disconnects, and cancellation do not refund it. Later HTTP requests receive 409; later WebSocket turns receive `diagnostic_session_consumed`. A new session requires an explicit server restart. There is no reset endpoint. Run one worker without hot reload so an automatic worker reload cannot silently initialize another session.

Verification includes concurrent claims from HTTP and WebSocket sources (exactly one wins), cancellation after claim (still consumed), a mocked HTTP request followed by a refused second route, and a WebSocket voice turn followed by a refused second WebSocket turn and HTTP request. Existing browser-auth, WebSocket streaming, and audio tests remain in the suite.

- Python tests: **56 passed**, 16 dependency/deprecation warnings.
- `compileall app tests`: passed.
- `node --check app/frontend/app.js`: passed.
- `git diff --check`: passed; only Git line-ending normalization warnings were emitted.
- No `.env` contents were displayed or changed. No push, deploy, or firmware flash occurred.

## User-run voice turn observed in logs

The user reported hearing approximately 1–2 seconds of Bella's voice. Edge visibly showed a complete assistant text response alongside the diagnostic banner **“FIRST-PHRASE-ONLY AUDIO — the rest of Bella's reply is text only.”** The backend trace confirms this is the configured one-phrase cap, not an audio-stream abort:

| Event | Trace `a455cc9e403d` |
| --- | ---: |
| Recording stop → final STT complete | 2.41 s |
| GPT request start after recording stop | 2.45 s |
| GPT request → HTTP response headers | 3.23 s |
| GPT request → first stream event | 3.25 s |
| GPT request → first nonempty text delta | 3.29 s |
| First phrase ready | 5.77 s after recording stop |
| Kokoro request → first valid MP3 prefix sent toward browser | 2.06 s |
| Recording stop → first valid MP3 prefix sent toward browser | 7.83 s |
| Kokoro stream completion | 7.99 s after recording stop |

The request context was 2 messages / 799 characters (rough estimate 200 input tokens); context preparation was 0.1 ms and provider-slot wait was effectively zero. The stream reported provider `OpenAI` and model `openai/gpt-4o-mini`. From the server-visible request-to-response interval, remote routing/inference and network transit cannot be separated.

One six-word phrase was queued. Later phrase queues (18 words and 8 words) were intentionally skipped by the diagnostic limit. Kokoro returned HTTP 200; the validated prefix was 1,389 bytes and the complete stream delivered 22,272 bytes. No Edge attempt, stream abort, or retry appears in the trace. Provider budget counters were exactly:

| Provider | Attempts | Limit |
| --- | ---: | ---: |
| OpenRouter STT | 1 | 1 |
| OpenRouter chat | 1 | 1 |
| Kokoro TTS | 1 | 1 |
| Edge TTS | 0 | 0 |

The server-side event-loop probe recorded 2,106 ms maximum lag and 25.5 ms average lag across 108 samples. The maximum spike may warrant follow-up, but it does not explain the short spoken duration: only one phrase was permitted. No browser-local monotonic playback-start measurement was collected in this inspection, and Codex did not independently listen to the audio. The reported 1–2 seconds is the user's observation, not a measured playback duration.

## Conclusion and safe next step

Bella's speech stopped after the first phrase because diagnostic mode deliberately caps TTS to one phrase to keep the live acceptance run within one Kokoro request. The remaining answer was text-only by design; the server trace shows the TTS stream itself completed. The one-shot session has been consumed, so another attempt in this process is rejected before provider dispatch.

To hear a complete response, a new session and a different explicitly authorized test configuration are needed. Keeping one Kokoro call would require synthesizing the entire reply as one audio input, which delays TTS until text generation finishes; allowing sentence-level streaming TTS would require more than the one-call budget. No such change or additional paid call was made here. Ask for explicit authorization and choose which behavior to test before creating another diagnostic session.
