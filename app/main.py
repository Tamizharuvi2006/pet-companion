import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api import chat, health, metrics, speech, tts, websocket
from app.core.config import get_settings
from app.device.http import router as device_http_router
from app.device.registry import DeviceRegistry
from app.device.websocket import router as device_websocket_router
from app.memory.short_term import ShortTermMemory
from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.edge_tts_service import EdgeTTSService
from app.services.metrics_service import MetricsService
from app.services.openrouter_stt_service import OpenRouterSTTService
from app.services.openrouter_tts_service import OpenRouterTTSService
from app.services.tts_service import TTSService
from app.services.whisper_service import WhisperService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    app.state.settings = settings
    app.state.device_registry = DeviceRegistry()
    app.state.memory = ShortTermMemory(settings.max_history_messages)
    app.state.ai = AIService(settings)
    app.state.context = ContextService()
    edge_tts = EdgeTTSService(settings)
    local_whisper = WhisperService(settings)
    tts_services: dict[str, TTSService] = {
        "edge": edge_tts,
        "kokoro": OpenRouterTTSService(settings, edge_tts),
    }
    try:
        app.state.tts = tts_services[settings.tts_provider]
    except KeyError as error:
        supported = ", ".join(tts_services)
        raise RuntimeError(
            f"Unsupported TTS_PROVIDER={settings.tts_provider!r}. Use one of: {supported}."
        ) from error
    app.state.whisper = OpenRouterSTTService(settings, local_whisper)
    app.state.metrics = MetricsService()
    # Preload once per server process. Transcription requests reuse this model.
    await app.state.whisper.load()
    await app.state.tts.load()
    try:
        yield
    finally:
        await app.state.ai.close()
        await app.state.tts.close()
        await app.state.whisper.close()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
app = FastAPI(title="Bella AI Cloud", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_metrics(request: Request, call_next: RequestResponseEndpoint) -> Response:
    started = perf_counter()
    response = await call_next(request)
    await request.app.state.metrics.record_request(
        request.method, response.status_code, perf_counter() - started
    )
    return response


app.include_router(health.router)
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
