# Bella Phase 1D — GPT TTFT and Strict Voice-Test Budget

**Status:** Offline investigation complete. No paid provider request, deployment, push, or hardware flash was performed. No actual latency improvement is claimed.

## Baseline evidence

The prior real browser turn (`6608fd098eb7`) reported:

| Stage | Observed |
| --- | ---: |
| Recording stop → first browser playback | 8.06 s |
| Final STT | 2.06 s |
| GPT request → first text | 4.60 s |
| First text → browser playback | 1.39 s |
| Kokoro usable MP3 prefix | approximately 1.29 s |
| Interim Tiny Whisper runs | 3.74 s and 2.52 s |
| Edge TTS | two HTTP 403 failures |
| Kokoro requests | two phrases in the same turn |

This is one observed turn, not a typical-latency estimate. GPT TTFT is a measured client-side interval, not a measurement of model inference alone. Its 4.60 seconds can include provider queue/routing, network setup and transit, server processing, and stream delivery. The old trace does not isolate those contributions, so the remote cause remains unconfirmed.

## Diagnosis and instrumentation

Privacy-safe monotonic trace stages were added around request preparation and provider calls. Logs include message count, context character count, a rough `characters / 4` input-token estimate, configured model, client-object new/reused status, provider-slot wait, request-to-response time, first event, first non-empty text delta, and time from first delta to stream completion. Provider/model routing metadata is logged only if a stream event exposes it.

For STT, timing now covers audio preparation, provider-slot wait, HTTP request-to-response, and response parsing. During a diagnostic WebSocket turn, an event-loop sampler records max/average scheduling lag and sample count. These intervals use the server process's monotonic clock. DNS, TLS, remote queue time, and model-only compute are not independently measured. “Reused client” means the SDK client object was reused; it does not prove the same TCP/TLS connection was reused.

Therefore the old 4.60-second GPT interval is now decomposable into useful client-observable stages on a future authorized run, but it cannot be retrospectively assigned to a specific provider/network/model cause.

## Interim Whisper behavior

Interim Faster-Whisper work runs through `asyncio.to_thread`. Cancelling the coroutine waiting on that worker does **not** stop inference already executing in its thread. The stop-recording trace reports whether a partial job is still pending; the thread logs worker start/finish and actual duration. A per-model thread lock prevents a later inference from overlapping a still-running cancelled worker on that same model.

With `WHISPER_INTERIM_ENABLED=false`, the WebSocket no longer schedules interim work and startup does not load the tiny interim model. Final cloud STT remains enabled; its local final fallback remains available. This is a diagnostic switch, not a permanent change to the normal default. No measured GPT improvement can be attributed to disabling interim work until a comparable live test is run.

## Diagnostic request budget

`VOICE_DIAGNOSTIC_MODE=true` enables a fresh atomic per-turn budget at provider dispatch boundaries:

| Provider | Maximum attempted requests |
| --- | ---: |
| OpenRouter STT | 1 |
| OpenRouter chat | 1 |
| OpenRouter Kokoro TTS | 1 |
| Edge TTS | 0 |

Reservations happen immediately before dispatch and are not refunded on error/cancellation. The OpenAI SDK's automatic retries are disabled in this mode. Startup also requires `TTS_PROVIDER=kokoro`; a non-`af_bella` voice/rate/pitch override is rejected. Kokoro's provider race and Edge fallback are bypassed, and the streaming turn queues at most one TTS phrase while continuing to stream the complete reply as text. The UI labels this explicitly as **FIRST-PHRASE-ONLY AUDIO**. Normal production behavior is not globally phrase-limited, and normal Edge support remains intact.

Diagnostic startup fails closed if credentials or the approved GPT-4o Mini / Whisper Large V3 Turbo / Kokoro `af_bella` configuration is absent or mismatched. The actual `.env` was not read or changed. The documented opt-in settings for the future test are:

```dotenv
VOICE_DIAGNOSTIC_MODE=true
WHISPER_INTERIM_ENABLED=false
```

Do not enable this or send audio until separately authorizing the one paid live turn. Each new diagnostic turn receives a new per-turn budget; keep the future acceptance procedure bounded to one recording/turn.

## Offline verification

The added offline tests use mocks/fakes only; they do not contact OpenRouter or Edge. They verify:

- Scaled STT → GPT → TTS timing and that first audio arrives while GPT is still generating.
- Thread-backed interim inference continues after waiter cancellation, while same-model inference stays serialized; the event-loop probe remains responsive during `to_thread` work.
- One phrase is synthesized while the complete reply text continues to stream.
- Concurrent attempts cannot exceed a provider's atomic budget; the second mocked STT/chat/Kokoro request is refused before another HTTP dispatch, and Edge is refused before connecting.
- A midstream audio failure does not trigger a second synthesis attempt.
- MP3-prefix validation requires complete consecutive frames; incomplete/non-MP3 prefixes are rejected.
- The diagnostic WebSocket labels first-phrase-only audio and does not queue a second phrase.

The offline scaled fake pipeline was run once during this phase. Its observed values were approximately:

| Fake stage | Elapsed |
| --- | ---: |
| STT | 26 ms |
| GPT time to first text | 60 ms |
| First text → first fake audio | 16 ms |
| Simulated recording stop → first fake audio | 103 ms |
| Turn completion | 180 ms |

The fake delays are deliberately set at 1/100 of the old 2.0 s / 4.6 s / 1.3 s stage values. These results validate asynchronous ordering only; they are **not** real provider latency, browser audible-start latency, nor comparable to the 8.06-second live baseline. No audio was listened to in this phase.

### Regression results

- Python test suite: **52 passed**, 14 warnings, 12.67 s.
- `compileall app tests`: passed.
- `node --check app/frontend/app.js`: passed.
- `git diff --check`: passed (Git printed line-ending normalization warnings only).
- Firmware build: not rerun; this phase made no firmware changes.

Offline coverage does not replay an actual Edge HTTP 403 response, stress-test memory under long recordings, or prove live provider/audio quality. The zero-call diagnostic guard is verified before any Edge network stream can start.

## Prepared single-turn live acceptance plan (not executed)

1. After separate explicit authorization, set the two diagnostic environment variables above in the user's local environment and restart the local Uvicorn process so it loads the new code/settings. Do not paste or expose the actual `.env` contents.
2. Confirm the UI shows diagnostic first-phrase-only audio and that the chosen settings are GPT-4o Mini, Whisper Large V3 Turbo, Kokoro `af_bella`; diagnostic mode rejects mismatches.
3. Make exactly one short microphone turn: “Bella, say hello to me.” Do not retry. The enforced maximum is one STT, one chat, one Kokoro request, zero Edge attempts; the assistant may continue returning text, but only the first phrase is synthesized.
4. Capture server `voice_timing` and `voice_provider_budget` entries plus browser `[bella_voice_timing]` entries by trace ID. Measure each side's intervals using its own monotonic offsets; do not subtract unsynchronized server/browser timestamps.
5. Record recording-stop → STT completion → first text → first playable TTS prefix → browser playback start, selected provider, and manual observations for silence, clipping, missing/repeated words, buffering pauses, and completion. Stop after the one turn and write the actual outcome separately; do not infer it from fake-provider tests.

## Remaining finding

The biggest opportunity is still the measured GPT first-text interval, followed by final STT. Whether GPT delay is mostly local queuing/event-loop/connection setup or upstream provider/network time is unknown until the new stage logs are collected on a real authorized turn. The interim-worker changes make overlap visible and let a future test remove Tiny CPU load without removing final STT. No configuration/model change has been shown to reduce actual audible latency yet.

At inspection, port 8000 was serving `/health` successfully from PID 15120 using `uvicorn app.main:app --host 127.0.0.1 --port 8000` without `--reload`. It was not restarted. That running process may not include these uncommitted changes; restart it before any future diagnostic run.
