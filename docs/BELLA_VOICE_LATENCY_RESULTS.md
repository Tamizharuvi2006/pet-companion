# Bella voice latency investigation and results

## Summary

The strongest code-level cause was not an LLM wait: the response text and bounded TTS worker were already concurrent, but each provider path waited for a complete MP3 file before the browser or ESP32 could receive audio. Browser playback queued file URLs; ESP32 conversion began only after the file existed. Historical logs also showed variable remote Kokoro completion (about 4.9–5.4 seconds for two phrases in one run, versus a separate 1.7-second request in another log). These old provider results are not comparable controlled trials.

The voice path now supports first-byte TTS streaming from Kokoro/OpenRouter and Edge, concurrent first-audio-byte selection when the existing race is enabled, browser MediaSource playback, and incremental MP3-to-PCM FFmpeg forwarding to the device. This is a structural latency improvement, not a claim of a measured faster audible response: live playback was not run here, and no paid provider request or ESP32 hardware test was made.

## Before and after

| Metric | Before: actual historical evidence | After: current code / verification |
| --- | --- | --- |
| LLM first token | 1.42 s in the 2026-08-01 23:17 pasted run | Not live-measured; logs first delta with `trace_id` |
| Interim Whisper wait before final STT | 1.60 s local Tiny Whisper in pasted logs, awaited before final STT | No mandatory serial wait for capture-ID clients (logic test passed; live timing not yet measured) |
| First phrase assembled | Not logged | Logged as `tts_phrase_ready`; target configurable to 4, 6, or 8 words (default 6); offline boundary tests added |
| Provider request start | Not consistently traced | Kokoro and Edge request-start stages logged |
| First provider audio bytes | Old path waited for complete file; no comparable first-byte measurement | Logged separately for Kokoro/Edge; race selects first provider bytes |
| First audio sent/delivered | Server `first_audio` was 8.208 s, meaning file readiness, not playback | Server byte/frame send and browser/device receive stages added; live not measured |
| First audible playback | Not measured | Browser `playing` event is instrumented; ESP32 first I²S write is instrumented, but acoustic timing is unverified |
| Full reply duration | 13.065 s in that historical server run | Not live-measured; final browser playback completion is instrumented |
| Audio underruns / packet gaps | Not measured | Firmware already checks sequence gaps, queue pressure, dropped frames; device validation remains required |

No percent-improvement figure is calculated because the before data is historical and the after audible-playback measurement is unavailable.

## Changes made

- Added privacy-safe per-turn trace IDs and monotonic server stage timing. Logs include stage names and non-sensitive metadata only; they do not include prompts, transcribed speech, audio, API keys, or provider URLs.
- Removed a confirmed serial wait from the browser voice path: the pasted run recorded 1.60 s for interim local Tiny Whisper, and source showed final transcription awaited that preview. Modern browser audio events now carry a capture ID; final STT starts without waiting on an unfinished interim preview, and late interim results are ignored after the final transcript or a newer recording. The local preview can still consume CPU in the background; this change removes its mandatory wait, not its compute cost.
- Added separate Kokoro/Edge request start, first audio byte, full stream completion, and winning-provider stages.
- Added a `TTS_FIRST_CHUNK_WORDS` setting (4–8, default 6), preferring a short natural punctuation boundary and never splitting a partial final word. Later speech still batches into natural 15–25-word phrases.
- Added provider MP3-byte streaming. The enabled Kokoro/Edge race chooses the first provider to return usable bytes and cleans up the losing stream asynchronously; the implementation does not wait for a complete losing audio file.
- Added browser capability negotiation and progressive MP3 appends to MediaSource, plus client timings for first text, first bytes, browser playback start, and playback completion. Clients without MP3 MediaSource continue to use the existing complete-file audio path.
- Added one incremental FFmpeg process per ESP32 TTS phrase, streaming MP3 input to bounded PCM16/16 kHz WebSocket frames. Firmware logs first received frame, first I²S write, and queue-drained timing with the trace ID. No additional FFmpeg process is started per PCM frame.
- Tuned the streaming FFmpeg MP3 demuxer with low-buffer/probe options after a local generated-audio test showed the default input buffering could delay PCM output until the encoded stream ended. The offline test now verifies PCM frames are forwarded before the test MP3 input is complete.
- Added stream-abort signaling so partial provider/decoder failures are visible and queued device audio can be flushed instead of mistaken for a complete chunk.

## Offline validation and live limits

Validation completed: `python -m compileall -q app tests`, `python -m pytest -q` (20 passed), `node --check app/frontend/app.js`, and a PlatformIO ESP32 Dev Module firmware build (successful; no flash/upload). The tests cover 4/6/8-word initial phrase selection, complete-word boundaries, natural short sentence boundaries, delivery of first TTS bytes while the fake LLM is still yielding tokens, choosing/cancelling the losing TTS stream by first bytes, modern-vs-legacy interim-STT waiting behavior, and real local FFmpeg incremental decoding from a generated MP3. They validate concurrency and framing logic, not network latency or perceived voice quality.

`pytest.ini` limits discovery to the project `tests/` directory because the checkout includes a vendored Piper benchmark tree with its own upstream test modules and test-only dependencies; those are not Bella's tests.

Not verified in this environment:

- A real Kokoro-only, Edge-only, existing-race, and optimized-race comparison. Do not treat a mocked test as a provider benchmark.
- Browser MediaSource decode/playback against actual provider bytes and the browser's autoplay policy.
- Railway networking/latency, a physical ESP32 connection, I²S acoustic start, or measured underruns.
- 100/150/200/300 ms physical-device startup-buffer comparisons. The firmware receives bounded 40 ms PCM frames and begins queued I²S playback as frames arrive, but buffer tuning needs real hardware and continuity checks.
- The target of 2–3 seconds from first usable LLM phrase to first audible sound. It remains a goal, not a guarantee.

## How to collect the next comparable run

1. Restart the local server after changing `TTS_FIRST_CHUNK_WORDS`; use the same input, provider settings, browser, network, and voice for each 4-, 6-, and 8-word run. Keep provider credentials in the local environment and never paste them into logs.
2. In server logs, group `voice_timing` lines by `trace_id`. Compare `tts_phrase_ready`, provider request/first-byte, `first_audio_bytes_sent_to_browser`, and `server_turn_complete`.
3. In browser DevTools console, group `[bella_voice_timing]` by the same ID. `first_text_delta_received` is the local baseline; compare first audio bytes, `first_playback_started`, and `playback_completed`. `playing` means the browser began playback, not that sound pressure was measured at the speaker.
4. For ESP32, group `voice_timing` firmware logs by ID and compare first device frame, first I²S write, queue-drained markers, sequence gaps, and dropped-frame count. These device elapsed offsets are device-local; do not subtract them from server/browser clocks.
5. Repeat each provider mode only within an explicitly approved usage budget. Record provider, model, voice, phrase target, network, input/reply length, and trial number so only comparable trials are contrasted.

Official implementation references: [OpenRouter text-to-speech endpoint tutorial](https://openrouter.ai/blog/tutorials/text-to-speech/) and [Edge TTS streaming implementation](https://github.com/rany2/edge-tts/blob/master/src/edge_tts/communicate.py).
