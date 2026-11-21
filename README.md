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

Normal Bella replies and cute pet-click phrases use Kokoro voice `af_bella`, an English voice that tested faster than `af_heart` in the local chunk benchmark. To prevent a slow Kokoro response from stalling a voice turn, Bella races Kokoro against `en-US-AnaNeural` Edge TTS and selects the first stream with two structurally complete MP3 frames; the slower stream is cancelled. This is a framing check, not proof of decoder success. If the selected stream later fails, the browser tears down that turn and offers an explicit retry instead of silently replaying partial speech. Set `TTS_RACE_ENABLED=false` to use Kokoro only, or `TTS_PROVIDER=edge` for Edge-only mode. `WHISPER_DEVICE=cpu` is the portable fallback default; only choose `cuda` when the matching CUDA 12 runtime is installed. Leave `WHISPER_LANGUAGE` blank for Tanglish auto-detection. Use a secure origin (localhost is accepted by browsers) and grant microphone permission.

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

WebSocket client events are `audio_chunk` (base64 WebM data), `stop_recording`, `text`, and `client_capabilities`. Server events include `status`, `transcript`, `reply_delta`, `reply`, `audio`, `tts_stream_start`, `tts_stream_end`, `tts_stream_abort`, `speech_coverage`, and `error`; progressive audio is carried in binary WebSocket messages between its start/end events. The server returns a session id with each reply; send it on later requests to continue the same history. For voice turns, Bella sends an early whole-word phrase to TTS while GPT continues generating. `TTS_FIRST_CHUNK_WORDS` controls the 4-8-word target (default 6); a short sentence boundary is preferred. Later output is batched into 15-25-word chunks, preferring `.`, `!`, or `?`. Browser clients that advertise MP3 MediaSource support receive provider audio bytes over the WebSocket as they arrive, so playback can begin before a complete TTS file or GPT reply exists. Other clients use the existing audio-file URL queue. The ESP32 path incrementally decodes the MP3 stream through one FFmpeg process per phrase and forwards bounded PCM frames to I²S.

Two mutually exclusive, process-wide one-shot voice test modes are available and disabled by default. `VOICE_DIAGNOSTIC_MODE=true` preserves the Phase 1E first-phrase-only test. `BOUNDED_FULL_VOICE_TEST=true` selects Phase 1F full-reply speech: one OpenRouter STT request, one GPT request, at most three Kokoro requests, and no Edge fallback/retries. Before a separately authorized test, turn off `VOICE_DIAGNOSTIC_MODE`, set `WHISPER_INTERIM_ENABLED=false` and `TTS_RACE_ENABLED=false`, then enable `BOUNDED_FULL_VOICE_TEST`. Startup validates the fixed GPT-4o Mini, Whisper Large V3 Turbo, Kokoro `af_bella`, and provider settings. Any paid HTTP or WebSocket operation consumes the same process latch; a restart is required for a fresh test. The local planner bounds each TTS input to 2,000 characters and reports incomplete audio rather than silently claiming full coverage. `speech_coverage` confirms only server-to-browser delivery, not that the browser decoded or audibly played it. Do not enable either mode for normal conversations.

Voice routes log the exact OpenRouter STT model, `Whisper final`, `Kokoro TTS`, `Edge TTS`, `openrouter`, and `total` duration. If a provider falls back, the logs say exactly which provider failed and which fallback was used.

## Browser access and public deployment

Local `ENVIRONMENT=development` keeps the browser convenient without a login. For any public/staging deployment, set `ENVIRONMENT=production`, `BELLA_ACCESS_PASSWORD` (a strong shared browser password of at least 16 characters), `BELLA_SESSION_SECRET` (random 32+ character signing secret), and `BELLA_ALLOWED_ORIGINS` (comma-separated exact HTTPS origins, with no paths). Startup fails closed if these are missing or malformed. The browser gets an HttpOnly, Secure, SameSite=Strict cookie; provider credentials never go to JavaScript. Keep secrets only in local `.env` or the hosting provider's secret-variable store.

HTTP paid routes, generated audio, metrics, and `/ws/chat` require that browser session in public mode. Rate limits, active-session caps, and provider concurrency are currently in-process; each Railway replica enforces its own limits. Before scaling to multiple replicas or exposing a high-traffic service, put a shared limiter (for example Redis) and edge/body-size limits in front of it. `/health` remains public for Railway health checks. ESP32 device-token authentication is independent and unchanged.

## Deploy to Render (Docker)

Create a Docker Web Service from the `main` branch and keep one instance for this in-process session/memory configuration. In the service settings, set the HTTP Health Check Path to `/health`; this is Render's readiness/recovery check, not a guarantee that a Free instance stays awake. Render provides `RENDER_EXTERNAL_URL` automatically.

If you specifically want a best-effort keepalive on a Free web service, add `RENDER_KEEPALIVE_INTERVAL_SECONDS=20` in Render's Environment settings. Bella will request its own public `/health` URL every 20 seconds after startup. This may prevent idle spin-down while those requests are routed to the service, but it cannot prevent platform-initiated restarts or outages. Keeping a Free instance running continuously uses about 720 of the workspace's 750 monthly Free instance hours, so use an always-on paid plan for reliable availability and leave the keepalive variable unset (or `0`) there. Add the same production authentication and OpenRouter variables described above in Render's Environment settings; do not commit `.env` or secrets.

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
2. In Railway **Variables**, set `ENVIRONMENT=production`, `BELLA_ACCESS_PASSWORD`, `BELLA_SESSION_SECRET`, and `BELLA_ALLOWED_ORIGINS` to the exact generated HTTPS domain, in addition to `OPENROUTER_API_KEY`, `TTS_PROVIDER=kokoro`, `OPENROUTER_STT_ENABLED=true`, `OPENROUTER_STT_MODEL=openai/whisper-large-v3-turbo`, `OPENROUTER_TTS_VOICE=af_bella`, and `OPENROUTER_TTS_CUTE_VOICE=af_bella`. Railway supplies `PORT`; do not hard-code it.
3. Deploy. The container starts with `uvicorn app.main:app --host 0.0.0.0 --port $PORT` and listens on Railway's assigned port.
4. Configure Railway's health check path as `/health`, then verify `/health` from the generated domain. `/metrics` requires a logged-in browser session in production. The browser test page is served from `/`.

Generated audio is stored on the container filesystem. Treat it as temporary on Railway; use an object store before relying on audio retention across deployments.

## Offline and browser tests

Install test-only tools without adding them to the production image, then run the Python and real-browser suites:

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests\browser -q
```

The browser acceptance test uses locally generated FFmpeg MP3 tones and fake in-process AI/STT/TTS services, then launches the installed Microsoft Edge channel to verify MediaSource decode/playback, phrase ordering, cleanup, and that first playback precedes LLM completion. It makes no paid-provider calls. If Microsoft Edge or FFmpeg is unavailable, that test skips; the offline service/parser tests remain separate from live audible-provider acceptance.

## ESP32 later

The physical device does not reuse the browser's WebM route. Its firmware sends mono PCM16LE/16 kHz frames to `/ws/device`; the server wraps captured audio for the existing STT service and converts the selected TTS stream to PCM16LE frames for the speaker. This reuses the current STT, GPT stream, memory, and TTS path instead of creating a second AI pipeline. Device authentication is required by default. For a short presentation demo only, setting `BELLA_DEVICE_AUTH_REQUIRED=false` allows any valid ESP32 `device_id` to connect to `/ws/device` with an empty token; this makes the public endpoint open to any internet client and can consume provider credits. Set it back to `true` after the demo. The `/api/device/*` management and camera endpoints remain token-authenticated.

See [the corrected proposed wiring and safety notes](docs/BELLA_PHASE1_WIRING.md), [protocol v1](docs/BELLA_PHASE1_PROTOCOL.md), [build/flashing steps](docs/BELLA_PHASE1_FLASHING.md), and [the acceptance checklist](docs/BELLA_PHASE1_TESTING.md). Firmware source lives in `firmware/bella_esp32/` and `firmware/bella_esp32_cam/`. Configure `BELLA_DEVICE_TOKENS` for the default authenticated mode; do not put provider keys in device firmware.

The firmware has not been flashed or physically tested. The current workspace had no serial COM port, and the TFT controller and ESP32-CAM board/sensor are not identified. Review [the results and blockers](docs/BELLA_PHASE1_RESULTS.md) before powering hardware; keep servo PWM disabled until power and mechanics are checked.
