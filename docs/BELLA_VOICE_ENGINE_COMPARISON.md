# Bella voice engine and device captions

## Current default

`VOICE_ENGINE_DEFAULT=gpt_audio_mini` makes GPT Audio Mini the default for the
browser and the ESP32 reply path. The browser selector still offers the older
OpenRouter cascade as a manual comparison/rollback option. The ESP32 uses the
single configured default, so Railway must also have this variable set to
`gpt_audio_mini`.

### Browser voice turns

- The browser streams microphone chunks to `/ws/chat` and finalizes the capture
  at the end of the utterance. The Audio Mini route converts the captured audio
  to mono WAV, then sends audio and the conversation in one OpenRouter request.
- Text deltas update the chat immediately. Audio deltas are decoded as PCM16 and
  sent to the browser as they arrive; this is a streamed response, not proof of
  a particular audible latency.
- Typed messages use the same model for reply text and audio output.

### ESP32 voice turns

1. INMP441 microphone audio reaches `/ws/device` as 16 kHz mono PCM frames.
2. The configured OpenRouter STT service transcribes the finished utterance.
3. GPT Audio Mini receives the transcript and conversation context, then streams
   reply text and 24 kHz mono PCM audio.
4. Text deltas travel to the display as they arrive. PCM is resampled by FFmpeg
   to the device protocol's 16 kHz format, then sent to the MAX98357A speaker.
5. Animated eyes continue rendering. If captions are enabled, reply text is
   overlaid only while the speaker is active; the preference is saved in ESP32
   NVS. Captions default to on.

The device STT step remains separate from GPT Audio Mini. The active recognizer
is selected by `OPENROUTER_STT_MODEL` (currently Grok STT 2.0 in `.env.example`)
with local Faster-Whisper as the configured fallback. Bella's system prompt asks
the model to reply in the language used by the user, including natural mixed
language. This is not a guarantee of support for every language: transcription,
voice quality, and language coverage must be checked with real utterances.
The current small TFT caption font is ASCII/Latin-oriented; other scripts are
shown as replacement marks until a Unicode font is added.

## Spoken caption controls

Say one of these explicit commands:

- “captions on”, “show captions”, or “show text” — show Bella's reply text while
  she speaks, alongside the animated face.
- “captions off”, “hide captions”, “hide text”, or “face only” — keep the face
  animation and hide reply text.

The setting is written to device NVS and survives a reboot when the flash write
succeeds. The device reports the selected state and whether it was persisted.
An older firmware that does not advertise `caption_overlay_v1` is not told that
the requested setting was applied.

## Model/API caveat

The configured OpenRouter model ID is `openai/gpt-audio-mini`. OpenRouter lists
text/audio input and output for it, but OpenAI marks GPT Audio Mini as deprecated,
states that streaming is unsupported on its API page, and lists a January 20,
2027 shutdown date. OpenRouter may expose provider behavior independently; this
does not establish that every account/provider route will stream or remain
available. Before release, verify account access and streaming on the selected
OpenRouter route. Keep `VOICE_ENGINE_DEFAULT` configurable and retain the current
cascade for rollback. OpenAI lists `gpt-audio-1.5` as a successor, but Bella has
not migrated or validated it as a drop-in replacement.

No paid-provider call or physical-device playback was performed for these code
changes. Local tests/builds do not establish live latency, language coverage,
audible continuity, or correct display rendering on the friend's exact TFT.
