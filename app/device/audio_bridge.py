import asyncio
from asyncio import IncompleteReadError, Lock
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter

from fastapi import WebSocket

from app.device.protocol import (
    AUDIO_TYPE_SPEAKER,
    PCM_FRAME_BYTES,
    SAMPLE_RATE_HZ,
    pack_audio_frame,
)
from app.services.tts_service import TTSAudioChunk
from app.services.voice_trace import mark_voice_stage

def resolve_audio_path(audio_dir: Path, audio_url: str) -> Path:
    """Resolve only an audio filename within the configured audio directory."""
    prefix = "/audio/"
    if not audio_url.startswith(prefix):
        raise ValueError("TTS returned an unsupported audio URL")
    path = (audio_dir / audio_url[len(prefix):]).resolve()
    if path.parent != audio_dir.resolve() or not path.is_file():
        raise ValueError("TTS audio file is not available")
    return path


async def stream_audio_as_pcm(
    websocket: WebSocket,
    audio_dir: Path,
    audio_url: str,
    *,
    turn_id: int,
    chunk_id: int,
    max_frame_bytes: int,
    send_lock: Lock,
) -> int:
    """Decode one already-synthesized MP3 to bounded 16 kHz PCM frames for I2S."""
    path = resolve_audio_path(audio_dir, audio_url)
    frame_bytes = min(PCM_FRAME_BYTES, max_frame_bytes)
    frame_bytes -= frame_bytes % 2
    if frame_bytes < 2:
        raise ValueError("configured device audio frame size is too small")

    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE_HZ),
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if process.stdout is None:
            raise RuntimeError("FFmpeg did not provide decoded audio")
        async with send_lock:
            await websocket.send_json(
                {
                    "type": "tts_chunk_start",
                    "version": 1,
                    "turn_id": turn_id,
                    "chunk_id": chunk_id,
                    "sample_rate_hz": SAMPLE_RATE_HZ,
                    "channels": 1,
                    "bits_per_sample": 16,
                    "frame_duration_ms": 40,
                    "codec": "pcm_s16le",
                }
            )

        sequence = 0
        total_bytes = 0
        while True:
            try:
                payload = await process.stdout.readexactly(frame_bytes)
            except IncompleteReadError as error:
                payload = error.partial
                if not payload:
                    break
            if len(payload) % 2:
                raise RuntimeError("FFmpeg returned a partial PCM sample")
            async with send_lock:
                await websocket.send_bytes(
                    pack_audio_frame(AUDIO_TYPE_SPEAKER, turn_id, sequence, payload)
                )
            total_bytes += len(payload)
            sequence += 1
            if len(payload) < frame_bytes:
                break
        return_code = await process.wait()
        if return_code != 0:
            raise RuntimeError(f"FFmpeg audio conversion exited with status {return_code}")
        if not sequence:
            raise RuntimeError("TTS audio decoded to an empty PCM stream")
        async with send_lock:
            await websocket.send_json({
                "type": "tts_chunk_end",
                "version": 1,
                "turn_id": turn_id,
                "chunk_id": chunk_id,
                "frame_count": sequence,
                "pcm_bytes": total_bytes,
            })
        return total_bytes
    finally:
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            await process.wait()
        # Device audio is ephemeral; browser URLs remain available as usual.
        path.unlink(missing_ok=True)


async def stream_mp3_chunks_as_pcm(
    websocket: WebSocket,
    mp3_chunks: AsyncIterator[TTSAudioChunk],
    *,
    turn_id: int,
    chunk_id: int,
    trace_id: str,
    max_frame_bytes: int,
    send_lock: Lock,
) -> int:
    """Pipe live MP3 bytes into one FFmpeg process and forward PCM as it decodes."""
    frame_bytes = min(PCM_FRAME_BYTES, max_frame_bytes)
    frame_bytes -= frame_bytes % 2
    if frame_bytes < 2:
        raise ValueError("configured device audio frame size is too small")

    started = perf_counter()
    mark_voice_stage("audio_conversion_started", provider="ffmpeg", chunk=chunk_id)
    process: asyncio.subprocess.Process | None = None
    reader_task: asyncio.Task[tuple[int, int]] | None = None
    total_mp3_bytes = 0
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            "-probesize",
            "32",
            "-analyzeduration",
            "0",
            "-f",
            "mp3",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE_HZ),
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("FFmpeg did not provide streaming pipes")

        await _send_locked(
            websocket,
            send_lock,
            {
                "type": "tts_chunk_start",
                "version": 1,
                "turn_id": turn_id,
                "chunk_id": chunk_id,
                "trace_id": trace_id,
                "sample_rate_hz": SAMPLE_RATE_HZ,
                "channels": 1,
                "bits_per_sample": 16,
                "frame_duration_ms": 40,
                "codec": "pcm_s16le",
            },
        )

        async def forward_pcm() -> tuple[int, int]:
            assert process is not None and process.stdout is not None
            sequence = 0
            total_pcm_bytes = 0
            first_pcm = True
            while True:
                try:
                    payload = await process.stdout.readexactly(frame_bytes)
                except IncompleteReadError as error:
                    payload = error.partial
                    if not payload:
                        break
                if len(payload) % 2:
                    raise RuntimeError("FFmpeg returned a partial PCM sample")
                if first_pcm:
                    mark_voice_stage(
                        "audio_conversion_first_pcm_frame",
                        duration_seconds=perf_counter() - started,
                        provider="ffmpeg",
                        chunk=chunk_id,
                        bytes=len(payload),
                    )
                    first_pcm = False
                if sequence == 0:
                    mark_voice_stage(
                        "first_audio_frame_sent_to_device",
                        duration_seconds=perf_counter() - started,
                        chunk=chunk_id,
                        bytes=len(payload),
                    )
                await _send_locked(
                    websocket,
                    send_lock,
                    pack_audio_frame(AUDIO_TYPE_SPEAKER, turn_id, sequence, payload),
                )
                total_pcm_bytes += len(payload)
                sequence += 1
                if len(payload) < frame_bytes:
                    break
            return sequence, total_pcm_bytes

        reader_task = asyncio.create_task(forward_pcm())
        async for piece in mp3_chunks:
            if not piece.data:
                continue
            if reader_task.done():
                await reader_task
            process.stdin.write(piece.data)
            await process.stdin.drain()
            total_mp3_bytes += len(piece.data)
        process.stdin.close()
        await process.stdin.wait_closed()
        sequence, total_pcm_bytes = await reader_task
        return_code = await process.wait()
        if return_code != 0:
            raise RuntimeError(f"FFmpeg streaming conversion exited with status {return_code}")
        if sequence == 0:
            raise RuntimeError("TTS audio decoded to an empty PCM stream")
        await _send_locked(
            websocket,
            send_lock,
            {
                "type": "tts_chunk_end",
                "version": 1,
                "turn_id": turn_id,
                "chunk_id": chunk_id,
                "trace_id": trace_id,
                "frame_count": sequence,
                "pcm_bytes": total_pcm_bytes,
            },
        )
        mark_voice_stage(
            "audio_conversion_complete",
            duration_seconds=perf_counter() - started,
            provider="ffmpeg",
            chunk=chunk_id,
            bytes=total_mp3_bytes,
        )
        return total_pcm_bytes
    finally:
        if reader_task is not None and not reader_task.done():
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except TimeoutError:
                process.kill()
                await process.wait()


async def _send_locked(
    websocket: WebSocket, send_lock: Lock, payload: dict[str, object] | bytes
) -> None:
    async with send_lock:
        if isinstance(payload, bytes):
            await websocket.send_bytes(payload)
        else:
            await websocket.send_json(payload)
