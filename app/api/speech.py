import uuid
from pathlib import Path
import logging
from time import perf_counter

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.api.chat import generate_reply
from app.api.deps import ai, context, memory, tts, whisper
from app.core.config import get_settings
from app.core.schemas import ChatResponse, TalkResponse
from app.memory.short_term import ShortTermMemory
from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.openrouter_stt_service import OpenRouterSTTService
from app.services.tts_service import TTSService
from app.services.request_limits import CapacityExceeded

router = APIRouter(tags=["speech"])
logger = logging.getLogger(__name__)


async def persist_upload(audio: UploadFile) -> Path:
    settings = get_settings()
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Please upload an audio file")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio.filename or "recording.webm").suffix or ".webm"
    destination = settings.upload_dir / f"{uuid.uuid4()}{suffix}"
    size = 0
    try:
        async with aiofiles.open(destination, "wb") as target:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="Audio upload is too large")
                await target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


@router.post("/stt")
async def stt(
    request: Request,
    audio: UploadFile = File(...), service: OpenRouterSTTService = Depends(whisper)
) -> dict[str, str]:
    try:
        async with request.app.state.voice_turn_gate.slot():
            path = await persist_upload(audio)
            started = perf_counter()
            try:
                text = await service.transcribe(path)
                logger.info("voice_timing stage=whisper seconds=%.3f", perf_counter() - started)
                return {"text": text}
            except RuntimeError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            finally:
                path.unlink(missing_ok=True)
    except CapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/talk", response_model=TalkResponse)
async def talk(
    request: Request,
    audio: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    stt_service: OpenRouterSTTService = Depends(whisper),
    short_term: ShortTermMemory = Depends(memory),
    ai_service: AIService = Depends(ai),
    context_service: ContextService = Depends(context),
    tts_service: TTSService = Depends(tts),
) -> TalkResponse:
    try:
        async with request.app.state.voice_turn_gate.slot():
            if session_id is not None and len(session_id) > 128:
                raise HTTPException(status_code=422, detail="Session ID is too long")
            turn_started = perf_counter()
            path = await persist_upload(audio)
            whisper_started = perf_counter()
            try:
                transcript = await stt_service.transcribe(path)
                logger.info("voice_timing stage=whisper seconds=%.3f", perf_counter() - whisper_started)
            except RuntimeError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            finally:
                path.unlink(missing_ok=True)

            result: ChatResponse = await generate_reply(transcript, session_id, short_term, ai_service, context_service)
            tts_started = perf_counter()
            try:
                audio_url = await tts_service.synthesize(result.reply)
                logger.info("voice_timing stage=tts seconds=%.3f", perf_counter() - tts_started)
            except RuntimeError as error:
                raise HTTPException(status_code=503, detail=str(error)) from error
            logger.info("voice_timing stage=total seconds=%.3f", perf_counter() - turn_started)
            return TalkResponse(session_id=result.session_id, transcript=transcript, reply=result.reply, audio_url=audio_url)
    except CapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
