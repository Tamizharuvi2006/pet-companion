# Bella AI Cloud

Browser-first voice-assistant backend built with Python 3.12 and FastAPI. The browser voice path remains available. A separate, versioned device WebSocket and ESP-IDF firmware projects have now been added for the proposed ESP32 DevKit and ESP32-CAM hardware. Camera/TFT profiles remain disabled until their exact boards/controllers are identified; servo PWM is disabled by default for safety.

## Run locally

1. Install Python 3.12 and [FFmpeg](https://ffmpeg.org/download.html) (required to decode browser WebM audio).
2. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

3. Put an OpenRouter key in `.env`, then start the server:

   ```powershell
   uvicorn app.main:app --reload --port 8000
   ```

Open [http://localhost:8000](http://localhost:8000). Bella sends the final recording to `openai/whisper-large-v3-turbo`; if that request is disabled, unavailable, or fails, it uses preloaded local Faster-Whisper `base`. The local `tiny` model remains the fast interim transcript engine. In the three-repeat, five-clip synthetic baseline, Whisper Turbo averaged 0.561 seconds (p95 0.634 seconds) versus Voxtral's 0.812 seconds (p95 1.296 seconds), with matching English transcripts and slightly lower tested cost. `OPENROUTER_TANGLISH_STT_MODEL=mistralai/voxtral-mini-transcribe` records the separate Tanglish experiment; it is not the normal route until real Tanglish/mic tests prove it is better.

Normal Bella replies and cute pet-click phrases use Kokoro voice `af_bella`, an English voice that tested faster than `af_heart` in the local chunk benchmark. To prevent a slow Kokoro response from stalling a voice turn, Bella races Kokoro against `en-US-AnaNeural` Edge TTS and uses the first completed audio; the slower result is cancelled. Set `TTS_RACE_ENABLED=false` to always wait for Kokoro, or `TTS_PROVIDER=edge` for an Edge-only deployment. `WHISPER_DEVICE=cpu` is the portable fallback default; only choose `cuda` when the matching CUDA 12 runtime is installed. Leave `WHISPER_LANGUAGE` blank for Tanglish auto-detection. Use a secure origin (localhost is accepted by browsers) and grant microphone permission.

## API

| Route | Purpose |
| --- | --- |
| `GET /health` | Service health check |
| `GET /metrics` | Prometheus-compatible HTTP/WebSocket counters and uptime |
| `POST /stt` | Multipart `audio` upload to text |
| `POST /chat` | JSON `{ "text", "session_id?" }` chat request |
| `POST /tts` | JSON `{ "text" }` speech synthesis |
| `POST /talk` | Multipart `audio` and optional `session_id`; complete voice turn |
| `WS /ws/chat` | Streaming browser voice/text conversation |
| `WS /ws/device` | Authenticated ESP32 PCM voice protocol v1 |
| `GET /api/device/{id}/status` | Bearer-authenticated device status |
| `GET /api/device/{id}/config` | Bearer-authenticated device audio/protocol config |
| `POST /api/device/{id}/camera/capture` | Authenticated proxy to configured camera JPEG capture |

WebSocket client events are `audio_chunk` (base64 WebM data), `stop_recording`, `text`, and `client_capabilities`. Server events include `status`, `transcript`, `reply_delta`, `reply`, `audio`, `tts_stream_start`, `tts_stream_end`, `tts_stream_abort`, and `error`; progressive audio is carried in binary WebSocket messages between its start/end events. The server returns a session id with each reply; send it on later requests to continue the same history. For voice turns, Bella sends an early whole-word phrase to TTS while GPT continues generating. `TTS_FIRST_CHUNK_WORDS` controls the 4-8-word target (default 6); a short sentence boundary is preferred. Later output is batched into 15-25-word chunks, preferring `.`, `!`, or `?`. Browser clients that advertise MP3 MediaSource support receive provider audio bytes over the WebSocket as they arrive, so playback can begin before a complete TTS file or GPT reply exists. Other clients use the existing audio-file URL queue. The ESP32 path incrementally decodes the MP3 stream through one FFmpeg process per phrase and forwards bounded PCM frames to I²S.

Voice routes log the exact OpenRouter STT model, `Whisper final`, `Kokoro TTS`, `Edge TTS`, `openrouter`, and `total` duration. If a provider falls back, the logs say exactly which provider failed and which fallback was used.

Kokoro 82M is billed by input characters at $0.62 per million characters: about $0.000062 for 100 characters, $0.00062 for 1,000 characters, and $0.00248 for 4,000 characters. Its 4K context is a request-size limit, not a $0.62 charge. `OPENROUTER_TTS_TIMEOUT_SECONDS=8` protects conversational latency by falling back to Edge if Kokoro is slow or fails.

## Choose the final STT model from evidence

Do not choose Voxtral or Whisper Turbo from one clip. Record the six named WebM clips in `benchmarks/stt/clips/` using the prompts and conditions in `benchmarks/stt/manifest.json`: quiet English, fan noise, Tanglish, fast speech, and male/female speakers. Then run three identical attempts per model:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_stt.py
```

The report at `benchmarks/stt/results/latest.json` contains the average and p95 transcription latency, word-error rate (WER), actual OpenRouter cost when returned, and each raw transcript. Pick the model that wins at least four of the six scenarios with acceptable Tanglish accuracy. Browser audio already arrives in 250 ms chunks; Tiny Whisper now refreshes the visible partial transcript every 750 ms. The final cloud transcription still waits for the completed utterance, avoiding repeated paid cloud STT calls.

`benchmarks/stt/synthetic_manifest.json` is only for a quick API baseline; it does not replace the real noisy-mic test. Run it with `--manifest benchmarks/stt/synthetic_manifest.json` after placing its generated clips in `benchmarks/stt/generated/`.

## Docker

```powershell
Copy-Item .env.example .env
# Set OPENROUTER_API_KEY in .env
docker compose up --build
```

The image installs `ffmpeg`, `git`, and `build-essential`. Its runtime command is:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The Docker health check calls `/health`; use `/metrics` to inspect request duration, request totals, active WebSocket connections, connected device count, and uptime. The compose file also declares opt-in Redis/PostgreSQL containers for the Phase 2 memory engine: `docker compose --profile memory up`. The current Phase 1 app uses an in-process `ShortTermMemory` implementation behind an interface; `LongTermMemory` and `MemoryRetriever` protocols are ready for the future PostgreSQL/ChromaDB adapters.

## Deploy to Railway

1. Push this directory to a Git repository and create a Railway service from it. Railway detects the `Dockerfile` automatically.
2. In Railway **Variables**, set `OPENROUTER_API_KEY`, `TTS_PROVIDER=kokoro`, `OPENROUTER_STT_ENABLED=true`, `OPENROUTER_STT_MODEL=openai/whisper-large-v3-turbo`, `OPENROUTER_TTS_VOICE=af_bella`, and `OPENROUTER_TTS_CUTE_VOICE=af_bella`. Railway supplies `PORT`; do not hard-code it.
3. Deploy. The container starts with `uvicorn app.main:app --host 0.0.0.0 --port $PORT` and listens on Railway's assigned port.
4. Configure Railway's health check path as `/health`, then verify `/health` and `/metrics` from the generated domain. The browser test page is served from `/`.

Generated audio is stored on the container filesystem. Treat it as temporary on Railway; use an object store before relying on audio retention across deployments.

## ESP32 later

The physical device does not reuse the browser's WebM route. Its firmware sends mono PCM16LE/16 kHz frames to `/ws/device`; the server wraps captured audio for the existing STT service and converts the existing winning Kokoro/Edge TTS file to PCM16LE frames for the speaker. This reuses the current STT, GPT stream, memory, and TTS race instead of creating a second AI pipeline.

See [the corrected proposed wiring and safety notes](docs/BELLA_PHASE1_WIRING.md), [protocol v1](docs/BELLA_PHASE1_PROTOCOL.md), [build/flashing steps](docs/BELLA_PHASE1_FLASHING.md), and [the acceptance checklist](docs/BELLA_PHASE1_TESTING.md). Firmware source lives in `firmware/bella_esp32/` and `firmware/bella_esp32_cam/`. Configure the matching `BELLA_DEVICE_TOKENS` server variable and ignored firmware `include/secrets.h`; do not put provider keys in device firmware.

The firmware has not been flashed or physically tested. The current workspace had no serial COM port, and the TFT controller and ESP32-CAM board/sensor are not identified. Review [the results and blockers](docs/BELLA_PHASE1_RESULTS.md) before powering hardware; keep servo PWM disabled until power and mechanics are checked.
