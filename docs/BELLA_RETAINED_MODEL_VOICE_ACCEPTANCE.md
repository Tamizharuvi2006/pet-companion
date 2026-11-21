# Retained-model voice acceptance

Date: 20 November 2026. Local development evidence only; no deployment or hardware flashing.

## Configuration and method

OpenRouter Grok STT 2.0, GPT-4o Mini, Kokoro 82M af_bella. No Edge fallback.
The backend accepts a completed recording, streams reply text, batches phrases,
and can prefetch substantial later phrases while preserving audio delivery order.
This is not continuous provider-side streaming transcription.

Three isolated Edge browser sessions replayed the same synthetic WAV through
Chromium's fake microphone. Each run allowed at most one STT, one chat, three
Kokoro attempts, and no Edge attempt. Browser times below are monotonic intervals
from recording stop. They are not server-to-browser clock differences.

| Browser milestone (seconds) | Run 1 | Run 2 | Run 3 | Median |
|---|---:|---:|---:|---:|
| Final transcript | 1.354 | 1.063 | 1.423 | 1.354 |
| First reply text | 3.468 | 2.741 | 3.166 | 3.166 |
| Playback started | 4.582 | 5.476 | 5.011 | 5.011 |
| Reply completion event | 7.634 | 7.488 | 5.045 | 7.488 |
| Playback completed | 14.919 | 16.689 | 12.469 | 14.919 |

All three emitted playback completion without JavaScript errors. Actual attempts:
three STT, three chat, eight Kokoro, zero Edge. Output text was generated afresh;
completion times include different spoken replies and cannot establish a matched
speed improvement. Billing totals were not independently retrieved.

Evidence: tmp/voice-live-retained-models.json, tmp/voice-live-repeat-2.json,
tmp/voice-live-repeat-3.json. These ignored local artifacts are not release files.
Reproduce only with explicit paid execution via
`python -m scripts.verify_live_voice --authorize-paid --output <new-path>`.

## Offline validation

- Full non-browser suite: 101 passed.
- Browser and device test selection: 16 passed (overlaps the full suite).
- Prefetch regressions show overlapping synthesis, ordered delivery, and closing
  both provider streams on cancellation. This does not prove live barge-in.
- Browser fixtures cover playback, injected audio errors, and a new turn during
  playback with simulated providers. No physical ESP32 speaker was measured.

## Remaining acceptance work

The 4.58-5.48 second startup range is functional, not instant conversation.
Earlier live Kokoro requests took over seven seconds, so three subsequent
successes do not establish tail-latency reliability. Browser completion events
do not prove voice quality, silence-free speech, or absence of missing words.
Live interruption/cancellation and silent-stall handling still need stronger
acceptance evidence. Firmware, pins, and credentials remain unchanged.

## Cancellable receive-loop follow-up

The server now processes voice generation in a separate task and cancels it
when the next capture begins, on a text turn, and on disconnect. A blocked-STT
regression proves the next capture can cancel an old provider before the next
recording ends and that the voice capacity slot is released. This is offline
provider cancellation evidence, not a live microphone barge-in quality score.
The updated full non-browser suite passed 102 tests; three browser scenarios
and two prefetch tests also passed.

A separate post-change live synthetic-microphone turn emitted final transcript
at 1.370 s, first text at 3.342 s, playback start at 6.854 s, and playback
completion at 16.644 s. It used one STT, one chat, three Kokoro calls and no
Edge. There were no JavaScript errors. Evidence:
tmp/voice-live-cancellable.json. This slower startup reinforces the observed
provider variability; cancellation is a responsiveness fix, not a demonstrated
reduction in first-reply latency.

## Delivery audit

| Requirement | Evidence and outcome |
|---|---|
| Retain models and OpenRouter only | Live traces use Grok STT 2.0, GPT-4o Mini, Kokoro af_bella; budget counts show zero Edge calls. No direct xAI key was introduced. |
| Short-reply batching | Regression coalesces a tiny opener and short tail into one TTS request, preserving full text. |
| Bounded concurrent synthesis | Two prefetch slots, two queued 16 KiB pieces per phrase; overlapping synthesis regression preserves delivery order. |
| Cancellation | New capture cancels a blocked old STT task; prefetch cancellation closes both open provider streams. Disconnect cancels the active voice task. |
| Browser playback | Three repeatability artifacts plus a separate post-cancellation artifact contain playback start and completion, no JavaScript errors. |
| Future ESP32 path | app/device/websocket.py uses the same stream_turn service; device tests pass. Physical output remains untested. |
| Whole suite | Final full invocation: 109 passed, 48 warnings in 64.06 seconds. Warnings are test dependency/deprecation notices. |
| Paper | output/pdf/Bella_IEEE_Voice_Evidence_Final.pdf and matching DOCX preserve the title and five-page layout, include the 6.85-second follow-up, and distinguish event timing from audible quality. All PDF pages visually reviewed. |
| Scope preservation | No deployment, push, flashing, servo activation, camera activation, or wiring changes. No secret values were printed. |

The retained-model optimization and measured software validation are delivered.
This does not certify ChatGPT-like responsiveness. The cloud transcription
endpoint still processes completed recordings, and Kokoro startup varies.
Further latency claims require new evidence, not removal of slow observations.
