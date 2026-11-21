import asyncio
import logging
import math
import struct
import uuid
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.device.audio_bridge import stream_mp3_chunks_as_pcm, stream_pcm24_chunks_as_device_audio
from app.device.display_settings import parse_caption_toggle
from app.device.protocol import (
    PCM_FRAME_BYTES,
    PROTOCOL_VERSION,
    SAMPLE_RATE_HZ,
    parse_audio_frame,
    parse_control_message,
)
from app.device.security import verify_device_token
from app.device.face import FaceReport, PlaybackReport
from app.services.streaming_turn_service import stream_turn
from app.services.tts_service import TTSAudioChunk
from app.services.voice_trace import (
    VoiceTrace,
    bind_voice_trace,
    reset_voice_trace,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["device"])
HELLO_TIMEOUT_SECONDS = 5.0
DEVICE_IDLE_TIMEOUT_SECONDS = 45.0
MIN_AUDIO_RMS = 12.0
ALLOWED_DEVICE_STATES = {
    "BOOTING",
    "CONNECTING",
    "IDLE",
    "LISTENING",
    "PROCESSING",
    "SPEAKING",
    "MUTED",
    "ERROR",
    "DISCONNECTED",
}


@router.websocket("/ws/device")
async def device_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    registry = websocket.app.state.device_registry
    send_lock = asyncio.Lock()
    websocket.state.device_send_lock = send_lock
    device_id: str | None = None
    session_id: str | None = None
    active_turn_id: int | None = None
    last_turn_id = -1
    expected_sequence = 0
    audio_samples = bytearray()
    recording_started = 0.0
    recording = False
    active_task: asyncio.Task[str] | None = None
    try:
        try:
            raw_hello = await asyncio.wait_for(
                websocket.receive_text(), timeout=HELLO_TIMEOUT_SECONDS
            )
            hello = parse_control_message(raw_hello)
        except (TimeoutError, RuntimeError, ValueError):
            await _send_error(websocket, "hello_required", "Send hello within 5 seconds")
            await websocket.close(code=4400)
            return

        settings = websocket.app.state.settings
        if (
            hello.type != "hello"
            or hello.version != PROTOCOL_VERSION
            or not hello.device_id
            or not hello.token
            or not verify_device_token(settings, hello.device_id, hello.token)
        ):
            await _send_error(websocket, "unauthorized", "Device authentication failed")
            await websocket.close(code=4401)
            return

        authenticated_device_id = hello.device_id
        connected = await registry.connected(
            authenticated_device_id,
            hello.firmware_version or "unknown",
            hello.capabilities,
            hello.sensors,
        )
        if not connected:
            await _send_error(websocket, "device_already_connected", "This device already has an active session", send_lock=send_lock)
            await websocket.close(code=4409)
            return
        device_id = authenticated_device_id
        connection_record = (await registry.snapshot(device_id))[0]
        await _send_json(websocket, send_lock,
            {
                "type": "device_ready",
                "version": PROTOCOL_VERSION,
                "device_id": device_id,
                "state": "IDLE",
                "connection_id": connection_record['connection_id'],
                "audio": {
                    "sample_rate_hz": SAMPLE_RATE_HZ,
                    "channels": 1,
                    "bits_per_sample": 16,
                    "codec": "pcm_s16le",
                    "frame_duration_ms": 40,
                    "frame_payload_bytes": PCM_FRAME_BYTES,
                },
                "max_recording_seconds": settings.device_max_recording_seconds,
            }
        )

        while True:
            try:
                incoming = await asyncio.wait_for(
                    websocket.receive(), timeout=DEVICE_IDLE_TIMEOUT_SECONDS
                )
            except TimeoutError:
                await _send_error(websocket, "heartbeat_timeout", "Send periodic ping messages", active_turn_id)
                await websocket.close(code=4408)
                break
            if incoming.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(incoming.get("code", 1000))
            if incoming.get("text") is not None:
                message = parse_control_message(incoming["text"])
                if message.version != PROTOCOL_VERSION:
                    await _send_error(websocket, "unsupported_version", "Control messages must use protocol version 1", message.turn_id)
                    continue
                if message.type == "ping":
                    if message.state is not None and message.state not in ALLOWED_DEVICE_STATES:
                        await _send_error(websocket, "invalid_state", "Unsupported device state", active_turn_id, send_lock)
                        continue
                    await registry.heartbeat(
                        device_id, state=message.state, sensors=message.sensors
                    )
                    await _send_json(websocket, send_lock,
                        {"type": "pong", "version": PROTOCOL_VERSION, "turn_id": active_turn_id}
                    )
                    command = await registry.take_command(device_id)
                    if command is not None:
                        await _send_json(websocket, send_lock, command)
                elif message.type.startswith('playback_'):
                    if not await websocket.app.state.rate_limiter.allow(f'playback:{device_id}', 120):
                        raise ValueError('Playback report rate exceeded')
                    payload = message.model_extra or {}
                    if payload.get('playback_version') != 1:
                        raise ValueError('Unsupported playback version')
                    report = PlaybackReport.model_validate({'event': message.type,
                        'turn_id': message.turn_id, 'sequence': message.sequence,
                        'basis': payload.get('basis'), 'estimated': payload.get('estimated')})
                    await registry.playback_report(device_id, report)
                elif message.type in {'face_report', 'face_ack'}:
                    if not await websocket.app.state.rate_limiter.allow(f'face-report:{device_id}', 120):
                        await _send_error(websocket, 'rate_limit', 'Face event rate exceeded')
                        continue
                    payload = message.model_extra or {}
                    if payload.get('face_version') != 1:
                        raise ValueError('Unsupported face version')
                    if message.type == 'face_ack':
                        command_id = payload.get('command_id')
                        if not isinstance(command_id, str) or len(command_id) != 32:
                            raise ValueError('Invalid command acknowledgement')
                        await registry.acknowledge(device_id, command_id)
                    else:
                        report = FaceReport.model_validate({
                            'expression': payload.get('expression'),
                            'sequence': message.sequence,
                            'touch_pad': payload.get('touch_pad')})
                        await registry.face_report(device_id, report.expression, report.sequence, report.touch_pad)
                elif message.type == 'display_settings_ack':
                    payload = message.model_extra or {}
                    captions_enabled = payload.get('captions_enabled')
                    if isinstance(captions_enabled, bool):
                        persisted = payload.get('persisted')
                        await registry.set_display_captions(
                            device_id,
                            captions_enabled,
                            persisted if isinstance(persisted, bool) else None,
                        )
                elif message.type == "sensor_event":
                    if message.state is not None and message.state not in ALLOWED_DEVICE_STATES:
                        await _send_error(websocket, "invalid_state", "Unsupported device state", active_turn_id, send_lock)
                        continue
                    await registry.heartbeat(
                        device_id, state=message.state, sensors=message.sensors
                    )
                elif message.type == "recording_start":
                    if settings.voice_test_enabled:
                        await _send_error(websocket, 'voice_test_browser_only', 'Device voice is disabled during bounded browser acceptance')
                        continue
                    if message.turn_id is None or recording:
                        await _send_error(websocket, "invalid_state", "Cannot start recording now", active_turn_id)
                        continue
                    if message.turn_id <= last_turn_id:
                        await _send_error(websocket, "stale_turn", "Turn IDs must increase for this connection", message.turn_id)
                        continue
                    if active_task is not None and not active_task.done():
                        await _send_error(websocket, "busy", "A conversation is already active", active_turn_id)
                        continue
                    if active_task is not None and active_task.done():
                        try:
                            session_id = active_task.result() or session_id
                        except asyncio.CancelledError:
                            pass
                        active_task = None
                    if not _valid_audio_format(message):
                        await _send_error(websocket, "audio_format", "Use mono 16 kHz PCM signed 16-bit little-endian", message.turn_id)
                        continue
                    active_turn_id = message.turn_id
                    await registry.begin_playback(device_id, active_turn_id)
                    last_turn_id = message.turn_id
                    expected_sequence = 0
                    audio_samples.clear()
                    recording_started = perf_counter()
                    recording = True
                    await registry.heartbeat(device_id, state="LISTENING")
                elif message.type == "recording_end":
                    if not recording or message.turn_id != active_turn_id:
                        await _send_error(websocket, "invalid_turn", "No matching recording is active", message.turn_id)
                        continue
                    if perf_counter() - recording_started > settings.device_max_recording_seconds:
                        recording = False
                        audio_samples.clear()
                        await _send_error(websocket, "recording_too_long", "Maximum recording duration exceeded", active_turn_id)
                        continue
                    recording = False
                    await registry.heartbeat(device_id, state="PROCESSING")
                    active_task = asyncio.create_task(
                        _process_turn(
                            websocket,
                            device_id,
                            active_turn_id,
                            bytes(audio_samples),
                            session_id,
                            recording_started,
                            send_lock,
                        )
                    )
                    audio_samples.clear()
                elif message.type == "cancel":
                    if active_turn_id is not None and message.turn_id not in (None, active_turn_id):
                        await _send_error(websocket, "invalid_turn", "Cancel turn id does not match", message.turn_id)
                        continue
                    await registry.cancel_playback(device_id)
                    recording = False
                    audio_samples.clear()
                    if active_task is not None and not active_task.done():
                        active_task.cancel()
                        await asyncio.gather(active_task, return_exceptions=True)
                    active_task = None
                    await registry.heartbeat(device_id, state="IDLE")
                    await _send_json(websocket, send_lock,
                        {
                            "type": "turn_complete",
                            "version": PROTOCOL_VERSION,
                            "turn_id": active_turn_id,
                            "cancelled": True,
                        }
                    )
                    active_turn_id = None
                else:
                    await _send_error(websocket, "unknown_message", "Unsupported device control message", message.turn_id)
            elif incoming.get("bytes") is not None:
                if not recording or active_turn_id is None:
                    await _send_error(websocket, "not_recording", "Start a recording before sending audio")
                    continue
                frame = parse_audio_frame(
                    incoming["bytes"], max_payload_bytes=settings.device_max_audio_frame_bytes
                )
                if frame.turn_id != active_turn_id or frame.sequence != expected_sequence:
                    await _send_error(websocket, "audio_sequence", "Audio turn or sequence is out of order", active_turn_id)
                    recording = False
                    audio_samples.clear()
                    continue
                expected_sequence += 1
                max_bytes = SAMPLE_RATE_HZ * 2 * settings.device_max_recording_seconds
                if len(audio_samples) + len(frame.payload) > max_bytes:
                    await _send_error(websocket, "recording_too_long", "Maximum recording duration exceeded", active_turn_id)
                    recording = False
                    audio_samples.clear()
                    continue
                audio_samples.extend(frame.payload)
                if perf_counter() - recording_started > settings.device_max_recording_seconds:
                    await _send_error(websocket, "recording_too_long", "Maximum recording duration exceeded", active_turn_id)
                    recording = False
                    audio_samples.clear()
            else:
                await _send_error(websocket, "empty_message", "Empty WebSocket message")
    except WebSocketDisconnect:
        logger.info("Device WebSocket disconnected")
    except (ValueError, KeyError) as error:
        await _send_error(websocket, "invalid_message", str(error))
    except Exception:
        logger.exception("Device WebSocket failed")
        try:
            await _send_error(websocket, "internal_error", "Device request could not be processed", active_turn_id)
        except Exception:
            pass
    finally:
        if active_task is not None and not active_task.done():
            active_task.cancel()
            await asyncio.gather(active_task, return_exceptions=True)
        if device_id is not None:
            await registry.disconnected(device_id)


async def _process_turn(
    websocket: WebSocket,
    device_id: str,
    turn_id: int,
    pcm_data: bytes,
    session_id: str | None,
    turn_started: float,
    send_lock: asyncio.Lock,
) -> str:
    settings = websocket.app.state.settings
    registry = websocket.app.state.device_registry
    trace = VoiceTrace(started_at=turn_started)
    trace_token = bind_voice_trace(trace)
    audio_path = settings.upload_dir / f"device-{uuid.uuid4()}.wav"
    try:
        rms = await asyncio.to_thread(_pcm_rms, pcm_data)
        if not pcm_data or rms < MIN_AUDIO_RMS:
            await _send_error(websocket, "silent_audio", "No usable microphone signal was detected", turn_id)
            await _send_json(websocket, send_lock, {"type": "turn_complete", "version": PROTOCOL_VERSION, "turn_id": turn_id, "cancelled": False})
            return session_id or ""

        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_write_pcm_wav, audio_path, pcm_data)
        stt_started = perf_counter()
        trace.mark("stt_started")
        transcript = await websocket.app.state.whisper.transcribe(audio_path)
        trace.mark("stt_complete", duration_seconds=perf_counter() - stt_started)
        await _send_json(websocket, send_lock,
            {"type": "transcript", "version": PROTOCOL_VERSION, "turn_id": turn_id, "text": transcript, "trace_id": trace.trace_id}
        )
        await registry.heartbeat(device_id, state="PROCESSING")
        captions_request = parse_caption_toggle(transcript)
        audio_instruction = None
        if captions_request is not None:
            device_records = await registry.snapshot(device_id)
            capabilities = device_records[0].get("capabilities", {}) if device_records else {}
            if capabilities.get("caption_overlay_v1") is True:
                command_id = uuid.uuid4().hex
                await registry.set_display_captions(device_id, captions_request)
                await _send_json(
                    websocket,
                    send_lock,
                    {
                        "type": "display_settings",
                        "version": 1,
                        "turn_id": turn_id,
                        "command_id": command_id,
                        "captions_enabled": captions_request,
                    },
                )
                state = "on" if captions_request else "off"
                audio_instruction = (
                    f"The user asked to turn reply captions {state}. The connected display accepted "
                    f"this setting. Briefly confirm it in the user's language, then stop."
                )
            else:
                audio_instruction = (
                    "The user asked to change reply captions, but this connected display's firmware "
                    "does not advertise caption overlay support. Kindly say the setting was not changed."
                )
        first_text_delta = True

        async def token_sink(token: str, active_session: str) -> None:
            nonlocal first_text_delta
            if first_text_delta:
                trace.mark("first_text_delta_sent_to_device")
                first_text_delta = False
            await _send_json(websocket, send_lock,
                {
                    "type": "reply_delta",
                    "version": PROTOCOL_VERSION,
                    "turn_id": turn_id,
                    "session_id": active_session,
                    "text": token,
                    "trace_id": trace.trace_id,
                }
            )

        async def audio_stream_sink(
            chunks: AsyncIterator[TTSAudioChunk], chunk_index: int
        ) -> None:
            # Sending PCM is not evidence that the device transmitter is playing.
            await registry.heartbeat(device_id)
            try:
                await stream_mp3_chunks_as_pcm(
                    websocket,
                    chunks,
                    turn_id=turn_id,
                    chunk_id=chunk_index,
                    trace_id=trace.trace_id,
                    max_frame_bytes=settings.device_max_audio_frame_bytes,
                    send_lock=send_lock,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await _send_json(
                    websocket,
                    send_lock,
                    {
                        "type": "tts_chunk_abort",
                        "version": PROTOCOL_VERSION,
                        "turn_id": turn_id,
                        "chunk_id": chunk_index,
                        "trace_id": trace.trace_id,
                    },
                )
                await _send_error(websocket, "audio_delivery", "Could not prepare speaker audio", turn_id)
                raise

        if settings.voice_engine_default == "gpt_audio_mini":
            pcm_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=6)

            async def pcm_sink(chunk: bytes) -> None:
                if device_audio_task.done():
                    await device_audio_task
                await pcm_queue.put(chunk)

            async def pcm_chunks() -> AsyncIterator[bytes]:
                while True:
                    item = await pcm_queue.get()
                    if item is None:
                        return
                    yield item

            device_audio_task = asyncio.create_task(
                stream_pcm24_chunks_as_device_audio(
                    websocket,
                    pcm_chunks(),
                    turn_id=turn_id,
                    chunk_id=1,
                    trace_id=trace.trace_id,
                    max_frame_bytes=settings.device_max_audio_frame_bytes,
                    send_lock=send_lock,
                )
            )
            ai = websocket.app.state.openrouter_audio_mini.create_turn(
                audio_sink=pcm_sink,
                trace_id=trace.trace_id,
                system_instruction=audio_instruction,
            )
            try:
                result = await stream_turn(
                    text=transcript,
                    session_id=session_id,
                    memory=websocket.app.state.memory,
                    context=websocket.app.state.context,
                    ai=ai,
                    tts=websocket.app.state.tts,
                    token_sink=token_sink,
                    audio_sink=None,
                    audio_stream_sink=None,
                    voice_trace=trace,
                    first_chunk_max_words=settings.tts_first_chunk_words,
                    spoken_reply=True,
                )
            except BaseException:
                if not device_audio_task.done():
                    await pcm_queue.put(None)
                await asyncio.gather(device_audio_task, return_exceptions=True)
                raise
            await pcm_queue.put(None)
            await device_audio_task
        else:
            result = await stream_turn(
                text=transcript,
                session_id=session_id,
                memory=websocket.app.state.memory,
                context=websocket.app.state.context,
                ai=websocket.app.state.ai,
                tts=websocket.app.state.tts,
                token_sink=token_sink,
                audio_sink=None,
                audio_stream_sink=audio_stream_sink,
                voice_trace=trace,
                first_chunk_max_words=settings.tts_first_chunk_words,
                spoken_reply=True,
            )
        await registry.audio_sent(device_id, turn_id)
        await _send_json(websocket, send_lock,
            {
                "type": "turn_complete",
                "version": PROTOCOL_VERSION,
                "turn_id": turn_id,
                "session_id": result.session_id,
                "reply": result.reply,
                "cancelled": False,
                "trace_id": trace.trace_id,
            }
        )
        trace.mark("server_turn_complete")
        return result.session_id
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Device conversation turn failed")
        await registry.failed(device_id, type(error).__name__)
        await _send_error(websocket, "turn_failed", "Bella could not complete this turn", turn_id)
        await _send_json(websocket, send_lock,
            {"type": "turn_complete", "version": PROTOCOL_VERSION, "turn_id": turn_id, "cancelled": False}
        )
        return session_id or ""
    finally:
        reset_voice_trace(trace_token)
        audio_path.unlink(missing_ok=True)
        # Device playback acknowledgments/sensor events own the output state.
        await registry.heartbeat(device_id)


def _valid_audio_format(message: object) -> bool:
    return (
        getattr(message, "sample_rate_hz", None) == SAMPLE_RATE_HZ
        and getattr(message, "channels", None) == 1
        and getattr(message, "bits_per_sample", None) == 16
        and getattr(message, "codec", None) == "pcm_s16le"
    )


def _pcm_rms(pcm_data: bytes) -> float:
    if len(pcm_data) < 2 or len(pcm_data) % 2:
        return 0.0
    sample_count = len(pcm_data) // 2
    square_sum = sum(sample * sample for (sample,) in struct.iter_unpack("<h", pcm_data))
    return math.sqrt(square_sum / sample_count)


def _write_pcm_wav(path: Path, pcm_data: bytes) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE_HZ)
        output.writeframes(pcm_data)


async def _send_error(
    websocket: WebSocket,
    code: str,
    message: str,
    turn_id: int | None = None,
    send_lock: asyncio.Lock | None = None,
) -> None:
    send_lock = send_lock or getattr(websocket.state, "device_send_lock", None)
    payload = {
        "type": "error",
        "version": PROTOCOL_VERSION,
        "code": code,
        "message": message,
        "turn_id": turn_id,
    }
    if send_lock is None:
        await websocket.send_json(payload)
    else:
        await _send_json(websocket, send_lock, payload)


async def _send_json(
    websocket: WebSocket, send_lock: asyncio.Lock, payload: dict[str, object]
) -> None:
    async with send_lock:
        await websocket.send_json(payload)
