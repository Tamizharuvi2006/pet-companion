import base64
import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter

import aiofiles
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.schemas import ChatResponse, WebSocketEvent
from app.services.streaming_turn_service import stream_turn
from app.services.tts_service import TTSAudioChunk
from app.services.voice_trace import (
    VoiceTrace,
    bind_voice_trace,
    reset_voice_trace,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])
PARTIAL_TRANSCRIPT_INTERVAL_MS = 750


async def emit(websocket: WebSocket, event_type: str, **payload: object) -> None:
    await websocket.send_json({"type": event_type, **payload})


async def _finish_interim_before_final(
    partial_task: asyncio.Task[None] | None, capture_id: str | None
) -> None:
    """Wait only for legacy clients that cannot discard a late partial result."""
    if partial_task is not None and (capture_id is None or partial_task.done()):
        await partial_task


@router.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.app.state.metrics.websocket_opened()
    chunks: list[bytes] = []
    captured_audio_ms = 0
    partial_task: asyncio.Task[None] | None = None
    last_partial_audio_ms = 0
    active_capture_id: str | None = None
    session_id: str | None = None
    streaming_mp3 = False
    try:
        while True:
            raw = await websocket.receive_text()
            event = WebSocketEvent.model_validate_json(raw)
            session_id = event.session_id or session_id
            if event.type == "client_capabilities":
                streaming_mp3 = event.streaming_mp3 is True
                continue
            if event.type == "audio_chunk" and event.data:
                active_capture_id = event.capture_id or active_capture_id
                chunks.append(base64.b64decode(event.data))
                captured_audio_ms += event.duration_ms or 250
                if (
                    captured_audio_ms - last_partial_audio_ms >= PARTIAL_TRANSCRIPT_INTERVAL_MS
                    and (partial_task is None or partial_task.done())
                ):
                    last_partial_audio_ms = captured_audio_ms
                    partial_task = asyncio.create_task(
                        _emit_partial_transcript(
                            websocket,
                            b"".join(chunks),
                            capture_id=active_capture_id,
                        )
                    )
                continue
            if event.type == "text" and event.data:
                session_id = (await _handle_text(websocket, event.data, session_id)).session_id
                continue
            if event.type == "stop_recording":
                capture_id = event.capture_id or active_capture_id
                # The local interim recognizer is only a UI hint. Do not put
                # its remaining CPU work in front of authoritative final STT.
                # New clients correlate late hints by capture_id; legacy
                # clients keep the original ordered behavior.
                await _finish_interim_before_final(partial_task, capture_id)
                session_id = await _handle_audio(
                    websocket,
                    chunks,
                    session_id,
                    streaming_mp3=streaming_mp3,
                    capture_id=capture_id,
                )
                chunks.clear()
                captured_audio_ms = 0
                partial_task = None
                last_partial_audio_ms = 0
                active_capture_id = None
                continue
            await emit(websocket, "error", message="Unknown or incomplete WebSocket event")
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except (ValueError, json.JSONDecodeError):
        await emit(websocket, "error", message="Invalid WebSocket event")
    except Exception:
        logger.exception("WebSocket processing failed")
        await emit(websocket, "error", message="Could not process this request")
    finally:
        await websocket.app.state.metrics.websocket_closed()


async def _emit_partial_transcript(
    websocket: WebSocket, audio: bytes, *, capture_id: str | None
) -> None:
    """Refresh the local interim transcript as browser audio continues arriving."""
    settings = websocket.app.state.settings
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"partial-{uuid.uuid4()}.webm"
    try:
        async with aiofiles.open(path, "wb") as audio_file:
            await audio_file.write(audio)
        transcript = await websocket.app.state.whisper.transcribe(path, interim=True)
        await emit(
            websocket,
            "partial_transcript",
            text=transcript,
            capture_id=capture_id,
        )
    except RuntimeError as error:
        logger.debug("Interim transcription skipped: %s", error)
    except WebSocketDisconnect:
        logger.debug("Interim transcription client disconnected")
    except Exception as error:
        logger.debug("Interim transcription delivery skipped: %s", type(error).__name__)
    finally:
        path.unlink(missing_ok=True)


async def _handle_text(
    websocket: WebSocket,
    text: str,
    session_id: str | None,
    send_ready: bool = True,
    stream_audio: bool = False,
    streaming_audio: bool = False,
    turn_started: float | None = None,
    voice_trace: VoiceTrace | None = None,
) -> ChatResponse:
    """Stream response text and optionally synthesize completed sentences in parallel."""
    trace = voice_trace or VoiceTrace(started_at=turn_started or perf_counter())
    trace_token = bind_voice_trace(trace)
    send_lock = asyncio.Lock()
    first_text_delta_logged = False

    async def emit_turn(event_type: str, **payload: object) -> None:
        async with send_lock:
            await emit(websocket, event_type, **payload)

    await emit_turn("status", text="Thinking...")

    async def send_token(token: str, active_session: str) -> None:
        nonlocal first_text_delta_logged
        if not first_text_delta_logged:
            trace.mark("first_text_delta_sent")
            first_text_delta_logged = True
        await emit_turn(
            "reply_delta",
            text=token,
            session_id=active_session,
            trace_id=trace.trace_id,
        )

    async def send_audio(audio_url: str, chunk_index: int) -> None:
        trace.mark("browser_audio_file_url_sent", chunk=chunk_index)
        await emit_turn("status", text="Speaking...")
        await emit_turn(
            "audio",
            url=audio_url,
            trace_id=trace.trace_id,
            chunk_index=chunk_index,
        )

    async def send_audio_stream(
        chunks: AsyncIterator[TTSAudioChunk], chunk_index: int
    ) -> None:
        trace.mark("browser_audio_stream_start_sent", chunk=chunk_index)
        await emit_turn(
            "tts_stream_start",
            codec="audio/mpeg",
            trace_id=trace.trace_id,
            chunk_index=chunk_index,
        )
        first_piece = True
        try:
            async for piece in chunks:
                if first_piece:
                    trace.mark(
                        "first_audio_bytes_sent_to_browser",
                        provider=piece.provider,
                        chunk=chunk_index,
                        bytes=len(piece.data),
                    )
                    first_piece = False
                async with send_lock:
                    await websocket.send_bytes(piece.data)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            trace.mark(
                "tts_stream_aborted",
                chunk=chunk_index,
                status=type(error).__name__,
            )
            await emit_turn(
                "tts_stream_abort",
                trace_id=trace.trace_id,
                chunk_index=chunk_index,
            )
            raise
        await emit_turn(
            "tts_stream_end",
            trace_id=trace.trace_id,
            chunk_index=chunk_index,
        )

    try:
        result = await stream_turn(
            text=text,
            session_id=session_id,
            memory=websocket.app.state.memory,
            context=websocket.app.state.context,
            ai=websocket.app.state.ai,
            tts=websocket.app.state.tts,
            token_sink=send_token,
            audio_sink=send_audio if stream_audio and not streaming_audio else None,
            audio_stream_sink=send_audio_stream
            if stream_audio and streaming_audio
            else None,
            voice_trace=trace,
            turn_started=turn_started,
            first_chunk_max_words=websocket.app.state.settings.tts_first_chunk_words,
        )
        trace.mark("browser_reply_complete_sent")
        await emit_turn(
            "reply",
            text=result.reply,
            session_id=result.session_id,
            trace_id=trace.trace_id,
        )
        if send_ready:
            await emit_turn("status", text="Ready")
        return result
    finally:
        reset_voice_trace(trace_token)


async def _handle_audio(
    websocket: WebSocket,
    chunks: list[bytes],
    session_id: str | None,
    *,
    streaming_mp3: bool = False,
    capture_id: str | None = None,
) -> str:
    if not chunks:
        await emit(websocket, "error", message="No audio was received")
        return session_id or ""
    settings = websocket.app.state.settings
    voice_trace = VoiceTrace()
    trace_token = bind_voice_trace(voice_trace)
    voice_trace.mark("voice_turn_received")
    turn_started = voice_trace.started_at
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"ws-{uuid.uuid4()}.webm"
    async with aiofiles.open(path, "wb") as audio_file:
        await audio_file.write(b"".join(chunks))
    try:
        await emit(websocket, "status", text="Processing...")
        whisper_started = perf_counter()
        voice_trace.mark("stt_started")
        transcript = await websocket.app.state.whisper.transcribe(path)
        voice_trace.mark(
            "stt_complete", duration_seconds=perf_counter() - whisper_started
        )
        await emit(
            websocket,
            "transcript",
            text=transcript,
            trace_id=voice_trace.trace_id,
            capture_id=capture_id,
        )
        result = await _handle_text(
            websocket,
            transcript,
            session_id,
            send_ready=False,
            stream_audio=True,
            streaming_audio=streaming_mp3,
            turn_started=turn_started,
            voice_trace=voice_trace,
        )
        await emit(websocket, "status", text="Ready")
        voice_trace.mark("server_turn_complete")
        return result.session_id
    finally:
        reset_voice_trace(trace_token)
        path.unlink(missing_ok=True)
