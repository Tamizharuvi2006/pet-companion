# Voice and responsive scrolling handoff

This release keeps all inference on the backend. The ESP32 sends mono 16 kHz
PCM, receives PCM converted from OpenRouter Kokoro MP3, and reports playback
progress. It does not need provider keys. Browser validation is not physical
speaker acceptance.

One Railway service hosts both independent voice protocols:

- Browser: `wss://<host>/ws/chat`, browser session authentication and MP3 playback.
- ESP32: `wss://<host>/ws/device`, device token authentication and 16 kHz PCM playback.

Do not point the ESP32 at the browser endpoint or expose provider credentials
in firmware. Both protocols share the configured models and bounded backend
provider capacity; separate endpoints do not imply infinite simultaneous capacity.

Normal voice replies now prefer a complete opening sentence or strong clause
boundary instead of cutting at the first-word target. A 25-word safety boundary
still limits run-on output. This preserves more prosodic context within each
Kokoro request; it does not guarantee a particular emotional voice delivery.
Diagnostic phrase limits remain unchanged. Short replies still coalesce and
substantial later phrases may prefetch while delivery remains ordered.

A live synthetic-microphone browser check of this grouping started playback
4.571 seconds after recording stop and completed at 13.478 seconds. Two Kokoro
requests were used. The browser emitted no JavaScript errors and no waiting or
stalled events after its playing event in this run. These events do not establish
human voice quality or prove zero acoustic pauses. Naturalness still requires
listening review, particularly for long replies and mixed-language speech.

## Preserved hardware safety

- Servo 1 remains GPIO13; Servo 2 remains GPIO12 and disabled by default.
- GPIO21 remains reserved. Shared I2S BCLK is GPIO26, WS GPIO25.
- Touch 4 is GPIO27 only after the physical wiring is checked.
- Exact board/flash identification and GPIO12 reset-pull verification are still
  required before enabling Servo 2. Do not infer safety from a successful build.
- Diagnostic and camera-disabled profiles built successfully. No flash,
  camera activation or servo activation was performed.

Follow BELLA_FRIEND_ONE_CLICK_SETUP.md for provision/flash steps and
BELLA_PHYSICAL_ACCEPTANCE_CHECKLIST.md for the physical result sheet.

## Backend configuration

Set MODEL_NAME=openai/gpt-4o-mini, OPENROUTER_STT_MODEL=x-ai/grok-stt-2.0,
OPENROUTER_TTS_MODEL=hexgrad/kokoro-82m and OPENROUTER_TTS_VOICE=af_bella.
Keep TTS_RACE_ENABLED=false, WHISPER_INTERIM_ENABLED=false and
WHISPER_PRELOAD_ENABLED=false. Copy only blank example variables; do not share
.env or provider keys with the hardware tester. Production requires the existing
browser authentication, HTTPS allowed-origin and device-token settings.

## Current measurements

Three browser sessions used one persistent backend with synthetic microphone
input. Playback began 4.830, 4.439 and 5.136 seconds after recording stop.
Playback ended at 13.822, 14.264 and 15.863 seconds respectively, including speech.
All completed without JavaScript errors. This is not a controlled comparison
against cold starts: reply text varied. Local evidence is in
tmp/voice-warm-session.json; it is not included in the source release.

The local endpoint now waits 800 ms after a short turn and 1100 ms after longer
speech, with quiet-ending hysteresis and a minimum speech-duration check.
Synthetic timing tests do not guarantee human speech cannot be clipped. The
friend should test pauses, quiet speech, fan noise, last words, interruptions,
speaker underruns, and playback acknowledgments on the real hardware.

The browser conversation scrolls at the left edge of its full-width viewport;
history and the composer stay fixed. Desktop and mobile layouts were checked.
