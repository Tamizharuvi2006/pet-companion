# Bella voice latency baseline

## Scope and evidence

This is a source-based baseline assembled on 2026-11-14 from the backend and firmware currently in this workspace, plus the server output pasted by the project owner. The pasted measurements are historical logs from 2026-08-01; they are useful evidence of the old path, but are not a controlled before/after benchmark of the current code. No paid provider requests or physical-device tests were run while preparing this report.

## Historical user-provided measurements

The most complete pasted voice turn (2026-08-01 around 23:17) reported:

| Stage | Historical measurement | What it measured |
| --- | ---: | --- |
| OpenRouter Whisper Large V3 Turbo | 1.315 s | Remote final transcription request |
| GPT first token | 1.42 s | Time to the first streamed text delta |
| GPT complete stream | 1.619 s | Complete model response stream |
| Kokoro phrase 1 | 5.369 s | Full TTS request/audio completion in the old file-based flow |
| Server `first_audio` | 8.208 s | Audio became available to the server, not confirmed browser playback |
| Kokoro phrase 2 | 4.855 s | Full second phrase TTS request/audio completion |
| Server `total` | 13.065 s | Turn work through speech generation; not acoustic playback completion |

That same pasted run also logged local interim Tiny Whisper at 1.60 s before the final OpenRouter STT request. Source inspection confirmed the WebSocket handler awaited the interim task before starting final transcription. This placed a non-authoritative local preview serially on the response path; it is now detached for capture-ID-capable clients while retaining late-result filtering. Legacy clients without capture IDs keep the old ordering for compatibility.

The timing relationships are consistent with STT + GPT + a complete first TTS file before sending audio, followed by later TTS phrases. They do not prove a current live-provider bottleneck by themselves.

An earlier pasted run at 23:04 showed OpenRouter STT at 1.469 s, GPT at 4.279 s, Kokoro racing/failing and Edge fallback at 2.20 s for a phrase. Its logged `first_audio` was 13.833 s and total was 22.207 s. The separate run is not directly comparable: provider/network performance differed and the first TTS attempt timed out before falling back.

## What the source path showed

- `app/services/streaming_turn_service.py` already ran an ordered, bounded TTS worker concurrently with GPT streaming. The old first phrase could wait for a word threshold or punctuation; later phrases used 15–25 words.
- The old active TTS interface returned a URL only after synthesis finished. Kokoro used a complete HTTP response body and Edge used a save-to-file operation. Thus GPT text could stream while the browser/device still waited for a complete MP3 phrase.
- The browser's old path queued complete audio-file URLs in an `HTMLAudioElement`; no first-byte-to-playback event was measured.
- The ESP32 path previously decoded completed MP3 files through FFmpeg before sending bounded PCM frames. It did not expose per-turn playback trace IDs.
- Kokoro is requested remotely through OpenRouter's `/audio/speech` endpoint. `OpenRouterTTSService.load()` intentionally does no model initialization, so there is no local Kokoro model reload or local GPU selection in this architecture. Edge TTS is also a remote streaming service. The local GPU therefore does not accelerate these TTS calls.
- Whisper processing precedes final GPT/TTS work. Interim local Whisper may run during capture, but it is not the TTS model and does not explain remote Kokoro synthesis time.
- The physical speaker's acoustic start and underruns cannot be inferred from server timestamps alone. ESP32 timing must use its own monotonic clock and physical playback still needs on-device verification.

## Measurement limitations

The pasted logs lack browser `playing` events, provider first-byte arrival, browser decode/playback buffering, ESP32 first PCM receive/I²S write, and a single comparable end-to-end trace. The historical server field called `first_audio` is therefore not “first audible sound.” Backend, browser, and ESP32 monotonic clocks must be analyzed independently; their absolute timestamps must not be subtracted from one another.

See [BELLA_VOICE_LATENCY_RESULTS.md](BELLA_VOICE_LATENCY_RESULTS.md) for the implementation changes, offline validation, and the live measurements still required.
