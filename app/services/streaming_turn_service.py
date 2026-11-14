import asyncio
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from time import perf_counter

from app.core.schemas import ChatResponse, Message
from app.memory.short_term import ShortTermMemory
from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.tts_service import TTSAudioChunk, TTSService
from app.services.voice_trace import (
    VoiceTrace,
    bind_voice_trace,
    reset_voice_trace,
)

logger = logging.getLogger(__name__)

FIRST_TTS_CHUNK_MIN_WORDS = 2
FIRST_TTS_CHUNK_MAX_WORDS = 6
MIN_TTS_CHUNK_WORDS = 15
MAX_TTS_CHUNK_WORDS = 25

TokenSink = Callable[[str, str], Awaitable[None]]
AudioSink = Callable[[str, int], Awaitable[None]]
AudioStreamSink = Callable[[AsyncIterator[TTSAudioChunk], int], Awaitable[None]]


def take_tts_chunks(
    buffer: str,
    *,
    allow_short_first_chunk: bool = False,
    first_chunk_max_words: int = FIRST_TTS_CHUNK_MAX_WORDS,
) -> tuple[list[str], str]:
    """Release an early whole-word phrase, then batch later speech naturally."""
    if first_chunk_max_words < FIRST_TTS_CHUNK_MIN_WORDS:
        raise ValueError("first chunk target must be at least two words")
    chunks: list[str] = []
    while buffer.strip():
        punctuation = list(re.finditer(r"[.!?]+(?:[\"')\]]*)?(?=\s|$)", buffer))
        words = list(re.finditer(r"\S+", buffer))
        complete_word_count = len(words)
        if buffer and not buffer[-1].isspace() and not any(
            mark.end() == len(buffer) for mark in punctuation
        ):
            complete_word_count -= 1
        if allow_short_first_chunk:
            first_boundary = next(
                (
                    mark
                    for mark in punctuation
                    if FIRST_TTS_CHUNK_MIN_WORDS
                    <= _word_count(buffer[: mark.end()])
                    <= first_chunk_max_words
                ),
                None,
            )
            if first_boundary is None and complete_word_count < first_chunk_max_words:
                break
            split_at = (
                first_boundary.end()
                if first_boundary is not None
                else words[first_chunk_max_words - 1].end()
            )
            allow_short_first_chunk = False
        elif complete_word_count >= MAX_TTS_CHUNK_WORDS:
            word_limit = words[MAX_TTS_CHUNK_WORDS - 1].end()
            suitable = [
                mark
                for mark in punctuation
                if MIN_TTS_CHUNK_WORDS
                <= _word_count(buffer[: mark.end()])
                <= MAX_TTS_CHUNK_WORDS
            ]
            split_at = suitable[0].end() if suitable else word_limit
        elif complete_word_count >= MIN_TTS_CHUNK_WORDS:
            suitable = [
                mark
                for mark in punctuation
                if _word_count(buffer[: mark.end()]) >= MIN_TTS_CHUNK_WORDS
            ]
            if not suitable:
                break
            split_at = suitable[0].end()
        else:
            break

        chunk = buffer[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        buffer = buffer[split_at:].lstrip()
    return chunks, buffer


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


async def stream_turn(
    *,
    text: str,
    session_id: str | None,
    memory: ShortTermMemory,
    context: ContextService,
    ai: AIService,
    tts: TTSService,
    token_sink: TokenSink,
    audio_sink: AudioSink | None,
    audio_stream_sink: AudioStreamSink | None = None,
    voice_trace: VoiceTrace | None = None,
    turn_started: float | None = None,
    first_chunk_max_words: int = FIRST_TTS_CHUNK_MAX_WORDS,
) -> ChatResponse:
    """Stream LLM output while a bounded TTS worker synthesizes early phrases."""
    trace = voice_trace or VoiceTrace(started_at=turn_started or perf_counter())
    trace_token = bind_voice_trace(trace)
    try:
        return await _stream_turn_bound(
            text=text,
            session_id=session_id,
            memory=memory,
            context=context,
            ai=ai,
            tts=tts,
            token_sink=token_sink,
            audio_sink=audio_sink,
            audio_stream_sink=audio_stream_sink,
            trace=trace,
            first_chunk_max_words=first_chunk_max_words,
        )
    finally:
        reset_voice_trace(trace_token)


async def _stream_turn_bound(
    *,
    text: str,
    session_id: str | None,
    memory: ShortTermMemory,
    context: ContextService,
    ai: AIService,
    tts: TTSService,
    token_sink: TokenSink,
    audio_sink: AudioSink | None,
    audio_stream_sink: AudioStreamSink | None,
    trace: VoiceTrace,
    first_chunk_max_words: int,
) -> ChatResponse:
    active_session = await memory.session_id(session_id)
    await memory.add(active_session, Message(role="user", content=text))
    messages = context.build_messages(await memory.get_history(active_session))
    started = perf_counter()
    trace.mark("llm_stream_request_start")
    reply_parts: list[str] = []
    sentence_buffer = ""
    audio_queue: asyncio.Queue[tuple[str, int] | None] | None = None
    tts_worker: asyncio.Task[None] | None = None
    chunk_index = 0
    first_tts_chunk_sent = False

    async def synthesize_queued_audio() -> None:
        nonlocal chunk_index
        assert audio_queue is not None
        while True:
            item = await audio_queue.get()
            if item is None:
                return
            sentence, current_chunk = item
            tts_started = perf_counter()
            trace.mark(
                "tts_synthesis_start",
                chunk=current_chunk,
                words=_word_count(sentence),
            )
            try:
                stream_method = getattr(tts, "stream_audio", None)
                if audio_stream_sink is not None and callable(stream_method):
                    await audio_stream_sink(stream_method(sentence), current_chunk)
                    trace.mark(
                        "tts_stream_sink_complete",
                        duration_seconds=perf_counter() - tts_started,
                        chunk=current_chunk,
                    )
                elif audio_sink is not None:
                    audio_url = await tts.synthesize(sentence)
                    trace.mark(
                        "tts_audio_file_ready",
                        duration_seconds=perf_counter() - tts_started,
                        chunk=current_chunk,
                    )
                    await audio_sink(audio_url, current_chunk)
                else:
                    # TTS is only needed when one of the client audio paths is active.
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("TTS chunk delivery failed; continuing streamed text")

    if audio_sink is not None or audio_stream_sink is not None:
        audio_queue = asyncio.Queue(maxsize=2)
        tts_worker = asyncio.create_task(synthesize_queued_audio())

    try:
        async for token in ai.stream_reply(messages):
            reply_parts.append(token)
            sentence_buffer += token
            await token_sink(token, active_session)
            if audio_queue is not None:
                chunks, sentence_buffer = take_tts_chunks(
                    sentence_buffer,
                    allow_short_first_chunk=not first_tts_chunk_sent,
                    first_chunk_max_words=first_chunk_max_words,
                )
                for chunk in chunks:
                    chunk_index += 1
                    trace.mark(
                        "tts_phrase_ready",
                        chunk=chunk_index,
                        words=_word_count(chunk),
                    )
                    await audio_queue.put((chunk, chunk_index))
                first_tts_chunk_sent = first_tts_chunk_sent or bool(chunks)
        if audio_queue is not None:
            if sentence_buffer.strip():
                chunk_index += 1
                trace.mark(
                    "tts_phrase_ready",
                    chunk=chunk_index,
                    words=_word_count(sentence_buffer),
                )
                await audio_queue.put((sentence_buffer.strip(), chunk_index))
            await audio_queue.put(None)
    except BaseException:
        if tts_worker is not None and not tts_worker.done():
            tts_worker.cancel()
        if tts_worker is not None:
            await asyncio.gather(tts_worker, return_exceptions=True)
        raise

    reply = "".join(reply_parts).strip()
    if not reply:
        if tts_worker is not None:
            tts_worker.cancel()
            await asyncio.gather(tts_worker, return_exceptions=True)
        raise RuntimeError("The AI provider returned an empty reply")
    trace.mark("llm_stream_complete", duration_seconds=perf_counter() - started)
    await memory.add(active_session, Message(role="assistant", content=reply))
    result = ChatResponse(session_id=active_session, reply=reply)
    if tts_worker is not None:
        await tts_worker
    trace.mark("voice_generation_complete")
    return result
