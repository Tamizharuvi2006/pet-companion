# Bella Phase 1F — Full-Voice Offline Results

**Date:** 2026-11-15
**Scope:** Offline implementation and validation only. No OpenRouter, Kokoro, Edge TTS, deployment, Git push, or firmware activity was performed in this phase.

## Result

The Phase 1E first-phrase diagnostic remains unchanged and separately selectable. A new, disabled-by-default `BOUNDED_FULL_VOICE_TEST` mode now speaks the full reply through a budgeted streaming plan. The code and synthetic browser path pass offline validation. This is not a live Kokoro acceptance result: real provider latency and audible Kokoro playback remain unmeasured.

## Modes and call limits

| Mode | OpenRouter STT | GPT | Kokoro | Edge | Speech behavior |
| --- | ---: | ---: | ---: | ---: | --- |
| `VOICE_DIAGNOSTIC_MODE=true` | 1 | 1 | 1 | 0 | Phase 1E first phrase only; complete reply remains text |
| `BOUNDED_FULL_VOICE_TEST=true` | 1 | 1 | at most 3 | 0 | Complete reply when it fits the bounded speech plan |

Both flags are mutually exclusive. Both use the same process-wide, concurrency-safe one-shot latch across HTTP and WebSocket operations. It is consumed before provider work and is not refunded after errors or cancellation; restart the server to create another test session. Provider reservations are made before dispatch. The full-voice budget refuses a fourth Kokoro attempt and every Edge attempt. SDK retries are disabled for these modes, and the Kokoro-only path does not race or fall back to Edge.

The application enforces a **2,000-character per-input safety cap** in bounded test modes. This is a local guard, not a claim about the provider's maximum. If the remaining tail exceeds it, the planner sends only a safe word/sentence prefix if available, keeps the complete text reply, and emits a `speech_coverage` event that explicitly marks audio as incomplete.

## Full-reply speech plan

- The first natural phrase is released as soon as the existing 2–6-word/punctuation rule permits it.
- At most two early phrases are queued while GPT is still streaming. The bounded queue has two waiting slots, and one serial worker preserves phrase order.
- After GPT completes, the remaining text is combined into the reserved final segment. No more than three TTS segments can be submitted.
- Text tokens are still streamed independently of TTS. Offline tests compare the resulting spoken-segment words with the full reply and verify no duplicate or missing words when the reply fits.
- Each turn owns its own speech queue. When another trace begins during old playback, the browser disposes the old media stream before starting the new one; it does not append the new turn to the old audio.
- `speech_coverage` means the server delivered the planned audio stream/file to the browser. It does **not** assert that a decoder successfully played it or that a person heard it. Browser playback errors are surfaced in the chat with the retry control.

## Event-loop investigation

The supplied Phase 1E trace `a455cc9e403d` reported:

- STT: 2.41 s
- GPT request to response headers: 3.23 s; request to first text: 3.29 s
- Kokoro first valid MP3 prefix: 2.06 s
- Recording stop to first valid prefix sent toward the browser: 7.83 s; this was not browser playback confirmation
- Maximum event-loop lag: 2,106 ms

That trace had no process CPU, thread-count, task-count, or lag-peak offset telemetry, so the 2,106 ms spike cannot be attributed to Whisper, a provider, TTS, or browser sending from that evidence alone.

Code inspection confirmed that Faster-Whisper inference and audio file reads already run off the event loop. The MP3 prefix validator was the concrete synchronous CPU path: it repeatedly rescanned a growing invalid prefix. Before the change, a synthetic 512 KB invalid stream took about **0.657 s** through repeated scans. Prefix framing checks now run in a worker thread, with frequent checks for ordinary small prefixes and geometric checkpoints for large malformed prefixes. The same synthetic stream completed in about **0.261 s** wall time, without holding the event loop for that scan. This is a mitigation for a worst-case path, not proof it caused the earlier spike.

New one-shot voice traces include event-loop max/average lag, the peak's turn-relative offset, process CPU percentage, peak active threads, and peak active tasks. Stage offsets can be compared with the lag peak in a future authorized trace. A synthetic 50 ms blocking sleep produced 26 ms peak loop lag; the same sleep in a worker thread produced 11 ms peak lag and observed the expected second thread. The short synthetic CPU-time measurement was below the local timer's useful resolution, so it is not reported as a utilization finding.

## Offline validation

- **73 tests passed** across the full Python suite, including the real-browser MediaSource tests with locally generated MP3 tones and fake services.
- Full-voice tests cover one short phrase, two/three/four-plus phrases, a reply below the first-chunk threshold, complete word ordering, over-cap tail reporting, TTS midstream failure without retry, cancellation, call-budget exhaustion, and one-shot session behavior.
- Browser tests cover ordered multi-segment playback while GPT continues, an injected playback error with visible recovery UI, and a second turn arriving during old playback without cross-turn mixing.
- Existing authentication/security tests passed as part of the suite.
- Python compilation passed: `python -m compileall -q app tests`.
- Frontend syntax passed: `node --check app/frontend/app.js`.
- `git diff --check` passed. Git emitted only line-ending conversion warnings.
- Firmware was not touched by this Phase 1F change, so no firmware build or flash was run.

## Remaining uncertainty

- No real OpenRouter STT, GPT, Kokoro, or Edge request was made; latency, cost, provider routing, and real voice continuity are unknown.
- Synthetic MP3 playback verifies browser sequencing and MediaSource behavior, not Kokoro decoding or the quality of Bella's generated voice.
- The historical event-loop spike remains unexplained. The new profiling is available for the next authorized run but has not been measured against a live provider turn.
- Process-level CPU percentage is an aggregate for the one-shot voice window, not per-provider CPU attribution. Trace offsets provide overlap evidence, not network/provider internals.
- The budget caps requests issued by Bella to OpenRouter. Any provider-internal routing/failover is outside the application's request counter.

## Preparation for the next authorized live test

No live test has been run or authorized here. For a future single microphone turn, keep the API key private and configure the local `.env` with:

```dotenv
VOICE_DIAGNOSTIC_MODE=false
BOUNDED_FULL_VOICE_TEST=true
WHISPER_INTERIM_ENABLED=false
TTS_RACE_ENABLED=false
TTS_PROVIDER=kokoro
OPENROUTER_STT_ENABLED=true
OPENROUTER_STT_MODEL=openai/whisper-large-v3-turbo
OPENROUTER_TTS_ENABLED=true
OPENROUTER_TTS_MODEL=hexgrad/kokoro-82m
OPENROUTER_TTS_VOICE=af_bella
MODEL_NAME=openai/gpt-4o-mini
```

Keep the valid `OPENROUTER_API_KEY` set locally. Restart the server and confirm startup logs say `mode=bounded_full_voice_test` with limits `stt:1,chat:1,kokoro:3,edge:0`. Then make exactly one microphone recording: **“Bella, tell me something nice.”** Do not click a pet voice, send a text message, or call another paid route first; those operations share and consume the one-shot latch. Record the server `voice_provider_budget` counts, server trace, browser `bella_voice_timing` offsets, playback completion, gaps, and a human listening assessment. The `speech_coverage` server event alone is not acceptance of audible playback.

Stop after this one turn. If it fails, preserve the trace and diagnose it before requesting another paid attempt.
