# Bella Railway deployment preparation

Prepared 2026-11-15. No deployment, push, real provider request or hardware flash was performed.

## Developer procedure (after review)

1. Review the dirty working tree and stage only intended paths. Never stage `.env`, `secrets.h`, firmware build outputs or generated managed components blindly.
2. Push the reviewed branch yourself. Create/select the Railway service with this backend as the root and the existing Dockerfile as its builder.
3. Use **one replica and one Uvicorn worker**. Registry, pending commands, one-shot acceptance latch, rate limits and short-term memory are process-local. Horizontal scaling needs shared state/ownership first.
4. Configure the service variables below before exposing it. Generate the public hostname in Railway; no hostname has been provisioned by this work. Set the exact resulting HTTPS origin in `BELLA_ALLOWED_ORIGINS`.
5. Set Railway healthcheck path `/health`. Docker starts `exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1`; Railway supplies `PORT`.
6. Verify health, login, unauthenticated API rejection, Face Studio and a fake/physical device handshake **without invoking voice**. Give the friend only the WSS hostname, device ID and device-specific token through a private channel.

| Variable | Hosted value / ownership |
| --- | --- |
| `ENVIRONMENT` | `production` (Docker default; explicitly set in Railway too) |
| `BELLA_ACCESS_PASSWORD` | Private browser-owner password, at least 16 characters |
| `BELLA_SESSION_SECRET` | Independent random signing secret, at least 32 characters |
| `BELLA_ALLOWED_ORIGINS` | Exact HTTPS origin; no paths, wildcards or credentials |
| `BELLA_DEVICE_TOKENS` | `device-001=<long random token>`; server and that device only |
| `OPENROUTER_API_KEY` | Backend only; never supply to friend/device/browser |
| `MODEL_NAME` | `openai/gpt-4o-mini` |
| `OPENROUTER_STT_MODEL` | `openai/whisper-large-v3-turbo` |
| `TTS_PROVIDER` | `kokoro` |
| `OPENROUTER_TTS_MODEL` | `hexgrad/kokoro-82m` |
| `OPENROUTER_TTS_VOICE` | `af_bella` |
| `VOICE_DIAGNOSTIC_MODE`, `BOUNDED_FULL_VOICE_TEST` | `false` for normal hosting; do not copy the local bounded process settings |
| `WHISPER_INTERIM_ENABLED` | `false` to avoid local interim inference on small cloud instances |
| `WHISPER_PRELOAD_ENABLED` | `false` skips local model downloads at startup; fallback can still lazy-load on failure |
| `BELLA_CAMERA_ENABLED` | `false` until separately validated |

The rest of the configuration reference is `.env.example`. Do not upload `.env` into the Docker image. Firmware and its ignored secrets are also excluded from Docker context. Device tokens can be rotated in server provisioning and the device's ignored file; restart/redeploy disconnects existing sessions.

## Transport and storage

ESP32 initiates outbound `wss://<host>/ws/device`; no LAN address/port forwarding is needed. Firmware uses the ESP certificate bundle and refuses insecure WS by default. Application pings run every 10 seconds; the server closes an inactive receive stream after 45 seconds. Reconnect is exponential, capped, with jitter.

The pasted plan's 60-second WebSocket timeout is not treated as a guaranteed Railway limit. Current [Railway WebSocket guidance](https://railway.com/guides/sse-vs-websockets) states upgraded WebSockets are exempt from request timeouts; reconnect remains needed for redeploys and network loss. [Railway healthcheck documentation](https://docs.railway.com/deployments/healthchecks) requires listening on `PORT` and notes deployment healthchecks are not continuous uptime monitoring.

Registry, commands and face events are intentionally ephemeral and reset on process restart. They are not durable history. Audio/upload files are scratch data, not a reliable permanent archive; do not treat a container filesystem as persistent memory. The memory placeholders are not a production durable database. A volume/object-store retention policy is a later concern if recordings must be preserved.

## Local commands (do not restart the existing bounded session casually)

```powershell
Set-Location 'D:\final year project\backend'
.\.venv\Scripts\python.exe -m pytest -q
# Only when intentionally starting a new process, with appropriate local env:
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Voice page: `http://localhost:8000/`; Face Studio: `http://localhost:8000/face.html`.
The existing running process was not restarted, so new Python routes will not appear there until an explicitly planned restart. Static face files can update independently.
