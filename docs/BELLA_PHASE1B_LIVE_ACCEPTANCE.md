# BELLA Phase 1B — Voice Streaming Acceptance

Date: 2026-11-14
Checkout: `D:\final year project\backend`
Status: local app is ready for a user-operated voice test; audible streaming acceptance is **not yet passed**.

## Local browser readiness

- Port `8000` was not listening when checked. Bella was started from the project `.venv` with Uvicorn on `127.0.0.1:8000`.
- `GET /health`, `GET /metrics`, and `GET /` returned HTTP 200. Health returned `status=ok` for `Bella AI Cloud` in `development`.
- Edge was opened at `http://127.0.0.1:8000/`. After navigation to the explicit port URL, the page showed **Ready** and the WebSocket-connected controls were enabled.
- The effective `TTS_FIRST_CHUNK_WORDS` setting read from application settings is `6`.
- No user speech or chat text was submitted. No paid STT, LLM, or TTS request was made.

## Offline checks

- `python -m pytest -q`: **20 passed** (5.95 s; four dependency deprecation warnings).
- `python -m compileall -q app tests`: passed.
- `node --check app/frontend/app.js`: passed.
- The offline suite includes a local FFmpeg-generated MP3-to-PCM streaming test and a mocked turn test showing the TTS worker can produce bytes while the fake LLM is still yielding. These prove local pipeline/concurrency properties only, not browser decoding or audible latency.

## Source inspection findings

### TTS provider race — acceptance concern remains

`app/services/openrouter_tts_service.py::_stream_race` starts Kokoro and Edge concurrently and selects the first provider whose iterator yields any non-empty `bytes`. It does **not** validate an MP3 frame, wait for a complete frame, or decode a playable prefix before selecting the provider. The current race test uses the literal fake payload `b"edge-first-bytes"`, so it demonstrates first-byte selection and loser cancellation, not valid audio selection. The concern in the acceptance prompt is confirmed: “first bytes” are not currently proven to be usable audio.

If a selected stream later errors, it emits an abort/error path; the current streaming race does not switch to the other provider after sending the winner's prefix. No provider was called during this inspection, so actual Kokoro/Edge framing and recovery behavior remain unverified.

### Browser streaming and fallback

- `app/frontend/app.js` checks `MediaSource.isTypeSupported("audio/mpeg")`, creates an `audio/mpeg` SourceBuffer in sequence mode, queues incoming binary WebSocket chunks, and appends the next chunk after each `updateend`.
- It requests playback when the first append is attempted and marks completion only after the server's final `reply` event and the pending append queue drains.
- If MediaSource reports unsupported, the browser uses the complete-file `audio` URL path.
- If MediaSource reports supported but SourceBuffer creation or append fails, the code logs a timing/error marker but does not switch that already-started stream to the complete-file fallback. Therefore that recovery path is not verified and is not currently implemented.
- Browser timing markers use `performance.now()` and report first received audio bytes, playback start, and completion. Actual decode, autoplay behavior, continuity, and audible output were not tested because that requires real provider audio and user interaction.

### Chunking, cancellation, and ordering

- The first phrase target is six words for the currently running app. The streaming-turn test verifies the first TTS output can occur before the fake LLM continues, and the offline phrase-boundary tests cover 4/6/8-word settings.
- A bounded TTS queue serializes phrase synthesis and applies backpressure; the WebSocket send lock serializes text events and binary audio frames.
- A provider-race loser is cancelled and cleaned up after winner selection. Mid-stream winner failure is reported as an aborted chunk, but there is no in-stream provider handoff.
- The legacy complete-file path remains available for browsers that do not advertise MP3 MediaSource support.

## Live playback acceptance — pending

No controlled voice turn was sent. Accordingly there are no real provider timings, no browser-local playback timings, and no manual audio-quality observations. Do not compare the historical server `first_audio` metric to audible playback: it measured server-side availability, not sound from Edge speakers.

Before a live run, the user should first confirm the intended provider configuration and authorize a bounded request budget. The browser is open and ready; the next user-operated short voice turn may trigger the configured final STT, LLM, and one or more TTS provider requests. No 4/6/8-word provider comparison is authorized or performed here.

Record a live run by grouping server `voice_timing` entries and browser `[bella_voice_timing]` console entries by `trace_id`. Compare STT start/completion, first LLM delta, first phrase ready, provider first bytes, browser first bytes, `first_playback_started`, and completion. Use each side's monotonic offsets independently; do not subtract unsynchronized server/browser absolute timestamps. Listen for silence, clipping, missing/repeated words, buffering pauses, and chunk ordering.

## Result

The local service and UI are available for a manual test, but Phase 1B real voice acceptance remains **incomplete**. The decisive open items are validation of a playable MP3 prefix before race selection, recovery behavior for MediaSource failures, and an explicitly authorized real-provider browser playback test. ESP32 flashing, servos, and camera activation were not part of this check.
