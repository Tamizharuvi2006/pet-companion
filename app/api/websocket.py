import base64
import asyncio
import binascii
import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter

import aiofiles
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.schemas import ChatResponse, WebSocketEvent
from app.services.event_loop_monitor import sample_event_loop_profile
from app.services.diagnostic_session import DiagnosticSessionConsumedError
from app.services.provider_budget import log_budget_summary, provider_budget_scope
from app.services.streaming_turn_service import stream_turn
from app.services.tts_service import TTSAudioChunk
from app.services.voice_trace import (
    VoiceTrace,
    bind_voice_trace,
    reset_voice_trace,
)
from app.services.browser_security import origin_is_allowed, websocket_principal
from app.services.request_limits import CapacityGate

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
    settings = websocket.app.state.settings
    if not origin_is_allowed(
        websocket.headers.get("origin"), websocket.headers.get("host"), settings
    ):
        await websocket.close(code=4403, reason="Origin is not allowed")
        return
    principal = websocket_principal(websocket)
    if principal is None:
        await websocket.close(code=4401, reason="Bella login required")
        return
    websocket_gate: CapacityGate = websocket.app.state.browser_websocket_gate
    if not await websocket_gate.acquire():
        await websocket.close(code=1013, reason="Bella is at connection capacity")
        return
    await websocket.accept()
    await websocket.app.state.metrics.websocket_opened()
    chunks: list[bytes] = []
    recording_bytes = 0
    recording_started_at: float | None = None
    recording_slot_owned = False
    discard_recording = False
    partial_task: asyncio.Task[None] | None = None
    last_partial_audio_ms = 0
    active_capture_id: str | None = None
    session_id: str | None = None
    streaming_mp3 = False
    voice_engine = settings.voice_engine_default
    diagnostic_recording_claimed = False
    active_turn: asyncio.Task[None] | None = None

    async def cancel_active_turn() -> None:
        nonlocal active_turn
        if active_turn is not None:
            active_turn.cancel()
            await asyncio.gather(active_turn, return_exceptions=True)
            active_turn = None

    async def generate_audio_turn(
        audio: list[bytes], capture_id: str | None, trace: VoiceTrace, selected_engine: str
    ) -> None:
        nonlocal session_id
        if not await websocket.app.state.voice_turn_gate.acquire():
            await emit(websocket, "error", code="capacity", message="Bella is busy; try again shortly")
            return
        try:
            async with provider_budget_scope(settings.voice_test_mode) as budget:
                try:
                    session_id = await _handle_audio(
                        websocket, audio, session_id, streaming_mp3=streaming_mp3,
                        capture_id=capture_id, voice_trace=trace, voice_engine=selected_engine,
                    )
                finally:
                    await log_budget_summary(budget, trace_id=trace.trace_id)
        except asyncio.CancelledError:
            trace.mark("voice_turn_cancelled")
            raise
        except Exception:
            logger.exception("Voice turn failed")
            await emit(websocket, "error", message="Could not process this voice turn")
        finally:
            await websocket.app.state.voice_turn_gate.release()

    async def reject_recording(message: str, code: str = "invalid_audio") -> None:
        nonlocal recording_bytes, recording_started_at, recording_slot_owned, discard_recording
        await emit(websocket, "error", code=code, message=message)
        chunks.clear()
        recording_bytes = 0
        recording_started_at = None
        active_capture_reset()
        if recording_slot_owned:
            await websocket.app.state.recording_gate.release()
            recording_slot_owned = False
        discard_recording = True

    def active_capture_reset() -> None:
        nonlocal active_capture_id, last_partial_audio_ms, diagnostic_recording_claimed
        active_capture_id = None
        last_partial_audio_ms = 0
        diagnostic_recording_claimed = False

    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw.encode("utf-8")) > ((settings.max_ws_audio_frame_bytes + 2) // 3) * 4 + 4096:
                await reject_recording("WebSocket message exceeds the frame size limit", "frame_too_large")
                continue
            event = WebSocketEvent.model_validate_json(raw)
            if event.type == 'cancel_recording':
                await cancel_active_turn()
                if partial_task is not None:
                    partial_task.cancel()
                    await asyncio.gather(partial_task, return_exceptions=True)
                    partial_task = None
                chunks.clear()
                recording_bytes = 0
                recording_started_at = None
                discard_recording = False
                active_capture_reset()
                if recording_slot_owned:
                    await websocket.app.state.recording_gate.release()
                    recording_slot_owned = False
                continue
            session_id = event.session_id or session_id
            if event.type == "client_capabilities":
                streaming_mp3 = event.streaming_mp3 is True
                if event.voice_engine is not None:
                    voice_engine = event.voice_engine
                await emit(websocket, "recording_limits", max_seconds=settings.max_ws_recording_seconds)
                await emit(websocket, "voice_engine_selected", voice_engine=voice_engine)
                continue
            if event.type == "audio_chunk":
                if discard_recording:
                    continue
                if not event.data:
                    await reject_recording("Audio frame is empty")
                    continue
                if recording_started_at is None:
                    await cancel_active_turn()
                    allowed = await websocket.app.state.rate_limiter.allow(
                        f"voice:{principal}", settings.voice_requests_per_minute
                    )
                    if not allowed:
                        await reject_recording("Voice request limit reached", "rate_limited")
                        continue
                    if not await websocket.app.state.recording_gate.acquire():
                        await reject_recording("Bella is at recording capacity", "capacity")
                        continue
                    recording_slot_owned = True
                    recording_started_at = perf_counter()
                active_capture_id = event.capture_id or active_capture_id
                encoded_limit = ((settings.max_ws_audio_frame_bytes + 2) // 3) * 4
                if len(event.data) > encoded_limit:
                    await reject_recording("Audio frame is too large", "frame_too_large")
                    continue
                try:
                    decoded = base64.b64decode(event.data, validate=True)
                except (binascii.Error, ValueError):
                    await reject_recording("Audio frame has invalid base64")
                    continue
                elapsed_ms = int((perf_counter() - recording_started_at) * 1000)
                if len(decoded) > settings.max_ws_audio_frame_bytes:
                    await reject_recording("Audio frame is too large", "frame_too_large")
                    continue
                if recording_bytes + len(decoded) > settings.max_ws_recording_bytes:
                    await reject_recording("Maximum recording size exceeded", "recording_too_large")
                    continue
                if elapsed_ms > settings.max_ws_recording_seconds * 1000:
                    await reject_recording("Maximum recording duration exceeded", "recording_too_long")
                    continue
                if settings.voice_test_enabled and not diagnostic_recording_claimed:
                    try:
                        await websocket.app.state.diagnostic_session.claim("websocket:audio")
                    except DiagnosticSessionConsumedError as error:
                        await reject_recording(str(error), "diagnostic_session_consumed")
                        continue
                    diagnostic_recording_claimed = True
                chunks.append(decoded)
                recording_bytes += len(decoded)
                if (
                    settings.whisper_interim_enabled
                    and elapsed_ms - last_partial_audio_ms >= PARTIAL_TRANSCRIPT_INTERVAL_MS
                    and (partial_task is None or partial_task.done())
                ):
                    last_partial_audio_ms = elapsed_ms
                    partial_task = asyncio.create_task(
                        _emit_partial_transcript(
                            websocket,
                            b"".join(chunks),
                            capture_id=active_capture_id,
                        )
                    )
                continue
            if event.type == "text" and event.data:
                await cancel_active_turn()
                if len(event.data) > 20_000:
                    await emit(websocket, "error", code="text_too_large", message="Message is too long")
                    continue
                allowed = await websocket.app.state.rate_limiter.allow(
                    f"chat:{principal}", settings.chat_requests_per_minute
                )
                if not allowed:
                    await emit(websocket, "error", code="rate_limited", message="Chat request limit reached")
                    continue
                if not await websocket.app.state.voice_turn_gate.acquire():
                    await emit(websocket, "error", code="capacity", message="Bella is busy; try again shortly")
                    continue
                try:
                    if settings.voice_test_enabled:
                        try:
                            await websocket.app.state.diagnostic_session.claim(
                                "websocket:text"
                            )
                        except DiagnosticSessionConsumedError as error:
                            await emit(
                                websocket,
                                "error",
                                code="diagnostic_session_consumed",
                                message=str(error),
                            )
                            continue
                    async with provider_budget_scope(settings.voice_test_mode) as budget:
                        try:
                            session_id = (await _handle_text(
                                websocket, event.data, session_id, voice_engine=voice_engine
                            )).session_id
                        finally:
                            await log_budget_summary(budget)
                finally:
                    await websocket.app.state.voice_turn_gate.release()
                continue
            if event.type == "stop_recording":
                if discard_recording:
                    discard_recording = False
                    chunks.clear()
                    recording_bytes = 0
                    recording_started_at = None
                    active_capture_reset()
                    continue
                capture_id = event.capture_id or active_capture_id
                if recording_started_at is not None and (
                    perf_counter() - recording_started_at > settings.max_ws_recording_seconds
                ):
                    await reject_recording("Maximum recording duration exceeded", "recording_too_long")
                    discard_recording = False
                    continue
                # The local interim recognizer is only a UI hint. Do not put
                # its remaining CPU work in front of authoritative final STT.
                # New clients correlate late hints by capture_id; legacy
                # clients keep the original ordered behavior.
                voice_trace = VoiceTrace()
                voice_trace.mark(
                    "recording_stop_received",
                    pending_jobs=int(partial_task is not None and not partial_task.done()),
                )
                await _finish_interim_before_final(partial_task, capture_id)
                try:
                    await cancel_active_turn()
                    active_turn = asyncio.create_task(
                        generate_audio_turn(list(chunks), capture_id, voice_trace, voice_engine)
                    )
                finally:
                    chunks.clear()
                    recording_bytes = 0
                    recording_started_at = None
                    active_capture_reset()
                    if recording_slot_owned:
                        await websocket.app.state.recording_gate.release()
                        recording_slot_owned = False
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
        await cancel_active_turn()
        if partial_task is not None and not partial_task.done():
            partial_task.cancel()
            await asyncio.gather(partial_task, return_exceptions=True)
        if recording_slot_owned:
            await websocket.app.state.recording_gate.release()
        await websocket_gate.release()
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
        if not transcript:
            return
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
    max_tts_phrases: int | None = None,
    full_voice_mode: bool = False,
    ai_override=None,
    voice_engine: str = "current",
    audio_mini_input: str | None = None,
) -> ChatResponse:
    """Stream response text and optionally synthesize completed sentences in parallel."""
    trace = voice_trace or VoiceTrace(started_at=turn_started or perf_counter())
    trace_token = bind_voice_trace(trace)
    send_lock = asyncio.Lock()
    first_text_delta_logged = False
    first_pcm_chunk_logged = False
    use_audio_mini = voice_engine == "gpt_audio_mini"

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

    async def send_pcm_audio(data: bytes) -> None:
        nonlocal first_pcm_chunk_logged
        if not data:
            return
        if not first_pcm_chunk_logged:
            trace.mark(
                "first_audio_bytes_sent_to_browser",
                provider="openrouter_gpt_audio_mini",
                bytes=len(data),
            )
            first_pcm_chunk_logged = True
            await emit_turn("status", text="Speaking...")
        async with send_lock:
            await websocket.send_bytes(data)

    async def send_speech_coverage(complete: bool, message: str) -> None:
        await emit_turn(
            "speech_coverage",
            complete=complete,
            text=message,
            trace_id=trace.trace_id,
        )

    try:
        if use_audio_mini:
            ai_override = websocket.app.state.openrouter_audio_mini.create_turn(
                audio_sink=send_pcm_audio,
                audio_input=audio_mini_input,
                trace_id=trace.trace_id,
            )
            await emit_turn(
                "pcm_stream_start",
                codec="pcm_s16le",
                sample_rate=24_000,
                channels=1,
                trace_id=trace.trace_id,
                model=websocket.app.state.settings.voice_audio_model,
            )
        result = await stream_turn(
            text=text,
            session_id=session_id,
            memory=websocket.app.state.memory,
            context=websocket.app.state.context,
            ai=ai_override or websocket.app.state.ai,
            tts=websocket.app.state.tts,
            token_sink=send_token,
            audio_sink=send_audio if stream_audio and not streaming_audio else None,
            audio_stream_sink=send_audio_stream
            if stream_audio and streaming_audio
            else None,
            voice_trace=trace,
            turn_started=turn_started,
            first_chunk_max_words=websocket.app.state.settings.tts_first_chunk_words,
            max_tts_phrases=max_tts_phrases,
            full_voice_mode=full_voice_mode,
            speech_coverage_sink=send_speech_coverage if full_voice_mode else None,
            spoken_reply=use_audio_mini,
        )
        if use_audio_mini:
            await emit_turn("pcm_stream_end", trace_id=trace.trace_id)
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
    except asyncio.CancelledError:
        if use_audio_mini:
            await emit_turn("pcm_stream_abort", trace_id=trace.trace_id)
        raise
    except Exception:
        if use_audio_mini:
            await emit_turn("pcm_stream_abort", trace_id=trace.trace_id)
        raise
    finally:
        reset_voice_trace(trace_token)


async def _handle_audio(
    websocket: WebSocket,
    chunks: list[bytes],
    session_id: str | None,
    *,
    streaming_mp3: bool = False,
    capture_id: str | None = None,
    voice_trace: VoiceTrace | None = None,
    voice_engine: str = "current",
) -> str:
    if not chunks:
        await emit(websocket, "error", message="No audio was received")
        return session_id or ""
    settings = websocket.app.state.settings
    voice_trace = voice_trace or VoiceTrace()
    trace_token = bind_voice_trace(voice_trace)
    voice_trace.mark("voice_turn_started")
    turn_started = voice_trace.started_at
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"ws-{uuid.uuid4()}.webm"
    loop_stop = asyncio.Event() if settings.voice_test_enabled else None
    loop_profile_started_at = perf_counter() if loop_stop is not None else None
    loop_probe = (
        asyncio.create_task(sample_event_loop_profile(loop_stop))
        if loop_stop is not None
        else None
    )
    try:
        async with aiofiles.open(path, "wb") as audio_file:
            await audio_file.write(b"".join(chunks))
        await emit(websocket, "status", text="Processing...")
        if voice_engine == "gpt_audio_mini":
            audio_input = await websocket.app.state.openrouter_audio_mini.prepare_audio(path)
            await emit(
                websocket,
                "voice_input_received",
                trace_id=voice_trace.trace_id,
                capture_id=capture_id,
            )
            result = await _handle_text(
                websocket,
                "[Voice message; transcript not retained]",
                session_id,
                send_ready=False,
                turn_started=turn_started,
                voice_trace=voice_trace,
                voice_engine=voice_engine,
                audio_mini_input=audio_input,
            )
            await emit(websocket, "status", text="Ready")
            voice_trace.mark("server_turn_complete")
            return result.session_id
        if settings.voice_audio_input_enabled and not settings.voice_test_enabled:
            ai_turn = await websocket.app.state.audio_reply.prepare(path)
            await emit(websocket, "voice_input_received", trace_id=voice_trace.trace_id,
                       capture_id=capture_id)
            result = await _handle_text(
                websocket, '[Voice message; transcript not retained]', session_id,
                send_ready=False, stream_audio=True, streaming_audio=streaming_mp3,
                turn_started=turn_started, voice_trace=voice_trace, ai_override=ai_turn)
            await emit(websocket, "status", text="Ready")
            return result.session_id
        if settings.voice_test_enabled:
            bounded_full_voice = settings.bounded_full_voice_test
            await emit(
                websocket,
                "diagnostic_audio_mode",
                text=(
                    "BOUNDED FULL-REPLY AUDIO — up to three Kokoro segments; playback is still being verified."
                    if bounded_full_voice
                    else "FIRST-PHRASE-ONLY AUDIO — the rest of Bella's reply is text only."
                ),
                trace_id=voice_trace.trace_id,
            )
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
            max_tts_phrases=(3 if settings.bounded_full_voice_test else 1)
            if settings.voice_test_enabled
            else None,
            full_voice_mode=settings.bounded_full_voice_test,
        )
        await emit(websocket, "status", text="Ready")
        voice_trace.mark("server_turn_complete")
        return result.session_id
    finally:
        if loop_stop is not None and loop_probe is not None:
            loop_stop.set()
            profile = await loop_probe
            voice_trace.mark(
                "event_loop_responsiveness",
                max_lag_ms=profile.max_lag_ms,
                max_lag_offset_ms=profile.max_lag_offset_ms,
                max_lag_turn_offset_ms=(
                    (loop_profile_started_at - voice_trace.started_at) * 1000
                    + profile.max_lag_offset_ms
                    if loop_profile_started_at is not None
                    else profile.max_lag_offset_ms
                ),
                avg_lag_ms=profile.average_lag_ms,
                samples=profile.samples,
                process_cpu_percent=profile.process_cpu_percent,
                max_active_threads=profile.max_active_threads,
                max_active_tasks=profile.max_active_tasks,
            )
        reset_voice_trace(trace_token)
        path.unlink(missing_ok=True)
