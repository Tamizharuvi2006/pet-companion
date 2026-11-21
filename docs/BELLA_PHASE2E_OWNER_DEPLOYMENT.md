# Bella Phase 2E — Owner Railway Deployment Guide

**This is preparation, not a deployment record.** Phase 2E did not access or change Railway. The local Docker engine was unavailable during this audit, so the image build remains an owner-side check.

## Before you deploy

1. Review `BELLA_PHASE2E_RELEASE_CANDIDATE.md` and its exact manifest. Stage only reviewed paths; never stage `.env`, generated `.bin` files, `.pio`, or `managed_components`.
2. Build the Docker image on a machine with Docker available. Confirm it starts with the command below and passes `/health` before deploying.
3. Push only after your explicit review/commit. Point the Railway service at this backend root and use the repository Dockerfile.
4. Keep **one Uvicorn worker and one active Railway replica**. Device registry, pending commands, rate limits, and memory/session state are process-local; scaling before moving these to shared state will break ownership and delivery.
5. In Railway, configure the variable names below in its secret/config store. Do not put values in this document, source files, firmware, screenshots, or logs.
6. Set the Railway healthcheck to `/health`; let Railway assign `PORT`. Set `BELLA_ALLOWED_ORIGINS` to the exact HTTPS browser origin generated for the service.
7. Verify health, authentication, rejected unauthenticated routes, `/metrics` after login, and an authenticated device WSS handshake without invoking voice. Voice/chat requests use paid providers; run them only after a separate owner-authorized acceptance test.

## Runtime contract

Docker uses Python 3.12 and installs the OS packages `ffmpeg`, `git`, and `build-essential`. Runtime is equivalent to:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

The Dockerfile shell expands Railway's `PORT` and uses `8000` only as a local fallback. The production image defaults `WHISPER_PRELOAD_ENABLED=false` and `WHISPER_INTERIM_ENABLED=false` to avoid model downloads and interim CPU inference during startup; local Compose values from `.env` override those defaults. Its container healthcheck calls `/health`. Do not add a second worker or replica until process-local state is migrated.

## Required variable names

Set these in Railway; this guide intentionally contains **names only**, never values:

- `ENVIRONMENT`
- `BELLA_ACCESS_PASSWORD`
- `BELLA_SESSION_SECRET`
- `BELLA_ALLOWED_ORIGINS`
- `OPENROUTER_API_KEY`
- `MODEL_NAME`
- `OPENROUTER_STT_ENABLED`
- `OPENROUTER_STT_MODEL`
- `OPENROUTER_TTS_ENABLED`
- `OPENROUTER_TTS_MODEL`
- `OPENROUTER_TTS_VOICE`
- `TTS_PROVIDER`
- `TTS_RACE_ENABLED`
- `WHISPER_PRELOAD_ENABLED`
- `WHISPER_INTERIM_ENABLED`
- `VOICE_DIAGNOSTIC_MODE`
- `BOUNDED_FULL_VOICE_TEST`
- `BELLA_CAMERA_ENABLED`

Set `WHISPER_PRELOAD_ENABLED` and `WHISPER_INTERIM_ENABLED` to false for a small Railway instance. The OpenRouter STT adapter then avoids downloading local Whisper models at startup; local final Faster-Whisper is lazy-loaded only if the cloud STT path fails. Confirm Railway memory headroom for that fallback before enabling it for production.

`PORT` is supplied by Railway; do not set a fixed public port. `BELLA_DEVICE_TOKENS` is needed only when provisioning a device. `BELLA_CAMERA_BASE_URL` and `BELLA_CAMERA_TOKEN` are optional and must remain unset while camera transport is unresolved. Optional model timeouts and request limits are documented in `.env.example`.

The public service must have a strong browser password, independent session-signing secret, and exact HTTPS origin. Startup rejects missing/weak browser settings and malformed origins. Cookies are HttpOnly, Secure in public mode, and SameSite=Strict. Keep `VOICE_DIAGNOSTIC_MODE` and `BOUNDED_FULL_VOICE_TEST` off for normal use; they are explicit one-shot acceptance modes, not production conversation defaults. Keep the optional camera disabled.

## Safe hosted checks

After an owner-reviewed deployment:

- `GET /health` should return healthy status without causing provider calls.
- The browser login should work only from the allowlisted origin; check the session cookie flags in browser devtools.
- Unauthenticated protected APIs and `/metrics` should be rejected; authenticated `/metrics` should return counters without secrets or transcripts.
- Device `wss://<host>/ws/device` should require its dedicated device ID/token. A device token is not a browser session and provider keys must never reach firmware.
- Do not invoke `/chat`, `/stt`, `/tts`, `/talk`, or voice WebSockets during smoke checks unless you explicitly authorize paid calls.
- Record Railway service/deployment identifiers, health result, resource plan, and worker/replica counts—but never tokens or secret values.

## Known deployment limitations

No hosted login, Railway memory plan, replica count, worker count, custom domain, variable presence, or live device handshake was observable in this audit. Railway topology and public behavior must therefore remain **pending** until checked in the owner account. Audio files are temporary container storage, and memory is not durable across restarts.
