import logging
import asyncio
import os
from contextlib import asynccontextmanager, suppress
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api import auth, chat, health, metrics, speech, tts, websocket
from app.api import face
from app.core.config import get_settings
from app.device.http import router as device_http_router
from app.device.registry import DeviceRegistry
from app.device.websocket import router as device_websocket_router
from app.memory.short_term import ShortTermMemory
from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.diagnostic_session import (
    DiagnosticSessionConsumedError,
    DiagnosticSessionLatch,
)
from app.services.edge_tts_service import EdgeTTSService
from app.services.provider_budget import log_budget_summary, provider_budget_scope
from app.services.metrics_service import MetricsService
from app.services.openrouter_stt_service import OpenRouterSTTService
from app.services.openrouter_tts_service import OpenRouterTTSService
from app.services.openrouter_audio_mini_service import OpenRouterAudioMiniService
from app.services.request_limits import CapacityGate, SlidingWindowRateLimiter
from app.services.browser_security import browser_principal
from app.services.render_keepalive import start_render_keepalive
from app.services.tts_service import TTSService
from app.services.whisper_service import WhisperService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_public_security()
    settings.validate_voice_diagnostic()
    if not settings.device_auth_required:
        logger.warning(
            "device_auth_disabled: /ws/device accepts tokenless public connections; "
            "restore BELLA_DEVICE_AUTH_REQUIRED=true after the demo"
        )
    app.state.diagnostic_session = DiagnosticSessionLatch(
        enabled=settings.voice_test_enabled
    )
    if settings.voice_test_enabled:
        tts_budget = 3 if settings.bounded_full_voice_test else 1
        logger.info(
            "voice_test_config_active mode=%s session_id=%s chat_model=%s stt_model=%s tts_provider=%s tts_model=%s tts_voice=%s interim_enabled=%s tts_race_enabled=%s provider_limits=stt:1,chat:1,kokoro:%s,edge:0",
            settings.voice_test_mode,
            app.state.diagnostic_session.session_id,
            settings.model_name,
            settings.openrouter_stt_model,
            settings.tts_provider,
            settings.openrouter_tts_model,
            settings.openrouter_tts_voice,
            settings.whisper_interim_enabled,
            settings.tts_race_enabled,
            tts_budget,
        )
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    app.state.settings = settings
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.provider_slots = asyncio.Semaphore(settings.max_concurrent_provider_requests)
    app.state.browser_websocket_gate = CapacityGate(settings.max_active_browser_websockets)
    app.state.recording_gate = CapacityGate(settings.max_active_recordings)
    app.state.voice_turn_gate = CapacityGate(settings.max_active_voice_turns)
    app.state.device_registry = DeviceRegistry()
    app.state.memory = ShortTermMemory(settings.max_history_messages)
    app.state.ai = AIService(settings, app.state.provider_slots)
    app.state.openrouter_audio_mini = OpenRouterAudioMiniService(
        settings, app.state.provider_slots
    )
    from app.services.audio_reply_service import AudioReplyService
    app.state.audio_reply = AudioReplyService(settings, app.state.provider_slots) if settings.voice_audio_input_enabled else None
    app.state.context = ContextService()
    edge_tts = EdgeTTSService(settings, app.state.provider_slots)
    local_whisper = WhisperService(settings)
    tts_services: dict[str, TTSService] = {
        "edge": edge_tts,
        "kokoro": OpenRouterTTSService(settings, edge_tts, app.state.provider_slots),
    }
    try:
        app.state.tts = tts_services[settings.tts_provider]
    except KeyError as error:
        supported = ", ".join(tts_services)
        raise RuntimeError(
            f"Unsupported TTS_PROVIDER={settings.tts_provider!r}. Use one of: {supported}."
        ) from error
    app.state.whisper = OpenRouterSTTService(settings, local_whisper, app.state.provider_slots)
    app.state.metrics = MetricsService()
    render_keepalive_task: asyncio.Task[None] | None = None
    # Preload once per server process. Transcription requests reuse this model.
    await app.state.whisper.load()
    await app.state.tts.load()
    render_keepalive_task = start_render_keepalive(
        os.getenv("RENDER_EXTERNAL_URL"), settings.render_keepalive_interval_seconds
    )
    try:
        yield
    finally:
        if render_keepalive_task is not None:
            render_keepalive_task.cancel()
            with suppress(asyncio.CancelledError):
                await render_keepalive_task
        await app.state.ai.close()
        await app.state.openrouter_audio_mini.close()
        if app.state.audio_reply is not None:
            await app.state.audio_reply.close()
        await app.state.tts.close()
        await app.state.whisper.close()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
app = FastAPI(title="Bella AI Cloud", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def browser_security_and_metrics(request: Request, call_next: RequestResponseEndpoint) -> Response:
    started = perf_counter()
    protected_operations = {
        "/chat": ("chat", "chat_requests_per_minute"),
        "/stt": ("stt", "stt_requests_per_minute"),
        "/tts": ("tts", "tts_requests_per_minute"),
        "/talk": ("talk", "talk_requests_per_minute"),
    }
    operation = protected_operations.get(request.url.path)
    is_protected_read = request.url.path == "/metrics" or request.url.path.startswith("/audio/")
    response: Response
    if operation or is_protected_read:
        try:
            principal = browser_principal(request)
            request.state.bella_principal = principal
            if operation:
                limit = getattr(request.app.state.settings, operation[1])
                allowed = await request.app.state.rate_limiter.allow(
                    f"{operation[0]}:{principal}", limit
                )
                if not allowed:
                    raise HTTPException(
                        status_code=429,
                        detail="Request limit reached; try again shortly",
                        headers={"Retry-After": "60"},
                    )
            if request.url.path in {"/stt", "/talk"}:
                content_length = request.headers.get("content-length")
                if content_length and int(content_length) > request.app.state.settings.max_upload_bytes + 1_048_576:
                    raise HTTPException(status_code=413, detail="Audio upload is too large")
        except (HTTPException, ValueError) as error:
            if isinstance(error, HTTPException):
                response = JSONResponse(
                    {"detail": error.detail},
                    status_code=error.status_code,
                    headers=error.headers,
                )
            else:
                response = JSONResponse({"detail": "Invalid request size"}, status_code=400)
        else:
            diagnostic_turn = bool(operation) and request.app.state.settings.voice_test_enabled
            if diagnostic_turn:
                try:
                    await request.app.state.diagnostic_session.claim(
                        f"http:{request.method}:{request.url.path}"
                    )
                except DiagnosticSessionConsumedError as error:
                    response = JSONResponse(
                        {
                            "code": "diagnostic_session_consumed",
                            "detail": str(error),
                        },
                        status_code=409,
                    )
                else:
                    async with provider_budget_scope(
                        request.app.state.settings.voice_test_mode
                    ) as budget:
                        try:
                            response = await call_next(request)
                        finally:
                            await log_budget_summary(budget)
            else:
                async with provider_budget_scope(False):
                    response = await call_next(request)
    else:
        response = await call_next(request)
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is not None:
        await metrics.record_request(
            request.method, response.status_code, perf_counter() - started
        )
    return response


app.include_router(health.router)
app.include_router(face.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(speech.router)
app.include_router(tts.router)
app.include_router(metrics.router)
app.include_router(websocket.router)
app.include_router(device_websocket_router)
app.include_router(device_http_router)

settings = get_settings()
app.mount("/audio", StaticFiles(directory=settings.audio_dir), name="audio")
app.mount("/", StaticFiles(directory="app/frontend", html=True), name="frontend")
