# Bella Railway Release Checklist

This is a release gate, not a deployment record. Phase 2D did not deploy or change Railway. Keep the existing app and protocol compatibility; make production changes only in the owner’s reviewed deployment.

## Before deployment

- [ ] Review `git status` and the exact diff. Phase 2D preserves local Phase 2C work; nothing was staged or pushed.
- [ ] Run the complete local test suite and supported firmware candidate builds from `BELLA_PHASE2D_SOFTWARE_COMPLETION.md`.
- [ ] Confirm Railway uses the repository Dockerfile, Python 3.12 and the container command `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (Docker’s checked-in startup may provide the equivalent single-worker form).
- [ ] Keep one Uvicorn worker and one active replica while `app.device.registry.DeviceRegistry` is process-local. Multiple workers/replicas would split live device state/commands.
- [ ] Verify only required environment variables are configured in Railway. Never paste the environment, `.env`, token values or API keys into logs/tickets.
- [ ] Set owner browser authentication and allowed origins; use HTTPS and secure cookies in public mode.
- [ ] Set `BELLA_DEVICE_TOKENS` as comma-separated `device_id=long-random-token` entries. Keep each ID exactly matched to USB-provisioned device identity. Revoke/rotate dedicated device tokens if exposed.
- [ ] Ensure OpenRouter and other paid provider keys remain server-side. Device firmware receives only its own revocable device token; no model-provider keys.
- [ ] Do not set unsafe browser/device debug, TLS bypass, or unrestricted audio/camera controls in production.
- [ ] If enabling the optional camera proxy, use a valid HTTPS `BELLA_CAMERA_BASE_URL` and a dedicated 16+ character `BELLA_CAMERA_TOKEN`. Public-mode startup and both capture routes reject plain HTTP; never route a public request directly to camera port 80.

## Device and service verification after owner deployment

- [ ] `/health` is healthy and `/metrics` is reachable only according to the configured public-surface policy.
- [ ] Browser owner login works only from allowed origins; unauthenticated device dashboard/doctor and control requests are rejected.
- [ ] Firmware authenticates over `wss://<railway-host>/ws/device`; no `ws://` fallback exists in the current provisioning path.
- [ ] Heartbeats, disconnect, reconnect and one-device ownership behave correctly.
- [ ] `/doctor.html` remains evidence-based; display visibility and audible speaker remain pending until physical human checks.
- [ ] Diagnostic reports omit tokens, transcripts, raw exception strings and camera image data.
- [ ] Voice provider calls are made only from explicit browser/device user interaction. Track cost/latency separately; do not use Health/Doctor checks for paid acceptance.

## Optional camera deployment caveat

The camera board currently exposes an authenticated **HTTP** snapshot service. Railway cannot ordinarily route to a private home/LAN address, and a bearer token over public plain HTTP is not acceptable. Keep camera capture disabled until an owner-approved reachable, transport-protected network path (for example a private tunnel or authenticated HTTPS gateway) exists; never expose the camera’s port 80 directly to the Internet.

## Release record

Record the reviewed commit, Railway deployment ID, health result, one-worker/replica configuration, configured device IDs (not tokens), and any pending hardware acceptance. Do not mark a local Docker build or offline test as hosted acceptance.
