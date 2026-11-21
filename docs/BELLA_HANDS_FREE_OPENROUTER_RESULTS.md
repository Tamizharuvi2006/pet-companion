# Hands-free voice and OpenRouter experiment

## Delivered behavior

Voice mode is opt-in, ends a turn on a local pause, and listens again after
playback. Microphone recording pauses during the reply to avoid speaker echo;
this is not a full-duplex realtime assistant. Idle silence is rotated locally
without paid turns. The server advertises its recording-duration limit and the
client submits before that deadline. This bounds each turn, not session length.
Long uninterrupted speech can be submitted mid-thought at that boundary.

Ending voice mode cancels server work and discards the partial capture.
Disconnect and background-tab transitions stop hands-free recording. Transport
limits still exist server-side; raw maximum-duration messages are not substituted
for Bella's conversational reply in hands-free recovery.

## Audio-input experiment

VOICE_AUDIO_INPUT_ENABLED=true selects a browser-only experimental path:
completed recording -> GPT Audio Mini via OpenRouter -> streamed reply -> Kokoro.
The existing Grok STT -> GPT-4o Mini -> Kokoro path remains the default. Both use
the same authenticated /ws/chat endpoint. ESP32 /ws/device remains unchanged.

The experimental model does not produce an independently verified transcript.
The UI displays Voice message and history stores an explicit untranscribed
placeholder. Therefore exact recall of earlier spoken details may be worse.
No audio archive is added. Cancellation closes the model stream and FFmpeg.
Audio conversion has a timeout and a decoded-duration/output-size bound.

Three corrected synthetic-input trials per architecture (full text generated
before one Kokoro request) yielded median first valid MP3 at 5.062 s for the
cascade and 2.808 s for audio-input. Every corrected MP3 decoded with FFmpeg.
An earlier harness run failed on the SDK stream-close method after reply text;
those six attempts did not reach TTS and are excluded, not counted as successes.

Hands-free browser playback with audio-input started at 5.023, 4.921 and 2.839 s
after recording stop, completing at 12.655, 11.590 and 8.600 s. Replies varied;
this is exploratory evidence, not a controlled statistical speedup or a human
microphone study. Network and provider variation remain. Browser completion does
not establish naturalness, absence of acoustic pauses, or ESP32 speaker timing.

Local artifacts: tmp/audio-pipeline-benchmark-corrected.json,
tmp/voice-combined-browser.json, tmp/voice-combined-repeat.json. They contain
synthetic test material, not user recordings, and are not a deployment payload.

## Configuration decision

Keep the cascade default until broader language, recall and listening checks
justify replacing it. The audio-input mode is available for local evaluation;
do not describe it as continuous streaming STT. Both modes use OpenRouter only,
with no direct-provider credentials and no Edge substitution.

No model selection or latency claim alone fixes conversational turn taking.
Realtime provider input and audio quality remain separate acceptance gates.

## Validation and delivery audit

- Earlier checkpoint: 114 passed, 50 dependency/deprecation warnings, 91.20 s;
  after the final buffered-frame change, three focused browser/cancellation
  tests passed, including explicit cancel_recording and stopped microphone tracks.
- Current release-candidate revalidation: 124 passed, 54 dependency/deprecation
  warnings, 66.09 s. No live provider calls were made during this revalidation.
- Long-turn test advertises a three-second server limit and verifies the client
  submits before the deadline without closing hands-free mode. It uses real
  MediaRecorder with a fake transport; provider playback is tested separately.
- Idle listening sent zero audio turns in the browser silence check. Live
  synthetic speech completed playback and resumed listening automatically.
- The browser and ESP32 remain on /ws/chat and /ws/device in one backend. No
  firmware pins, credentials, deployment, or hardware activation were changed.
- No instantaneous latency is promised. The experimental path is opt-in, not a
  silent model replacement. The existing default retains transcript history.

The delivered configuration provides bounded continuous sessions, not continuous
provider-side recognition or unlimited recording. A long turn may be submitted
before the user finishes the thought. Full-duplex interruption while speaking,
real-human naturalness and microphone behavior remain outside these measured
results and must not be inferred from the successful synthetic tests.
