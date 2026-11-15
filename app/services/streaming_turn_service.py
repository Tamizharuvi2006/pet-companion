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
from app.services.provider_budget import BOUNDED_FULL_TTS_MAX_INPUT_CHARS
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
SpeechCoverageSink = Callable[[bool, str], Awaitable[None]]


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


def _bounded_speech_prefix(text: str, max_chars: int) -> str:
    """Return the longest safe word/sentence prefix under the local text cap."""
    if len(text) <= max_chars:
        return text.strip()
    prefix = text[:max_chars]
    sentence_ends = list(re.finditer(r"[.!?]+(?:[\"')\]]*)?(?=\s|$)", prefix))
    if sentence_ends:
        return prefix[: sentence_ends[-1].end()].strip()
    split_at = max(prefix.rfind(" "), prefix.rfind("\n"), prefix.rfind("\t"))
    return prefix[:split_at].strip() if split_at > 0 else ""


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
    max_tts_phrases: int | None = None,
    full_voice_mode: bool = False,
    speech_coverage_sink: SpeechCoverageSink | None = None,
) -> ChatResponse:
    """Stream LLM output while a bounded TTS worker synthesizes early phrases."""
    if full_voice_mode and max_tts_phrases != 3:
        raise ValueError("Bounded full-voice mode requires exactly three available TTS slots")
    if full_voice_mode and audio_sink is None and audio_stream_sink is None:
        raise ValueError("Bounded full-voice mode requires a browser audio sink")
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
            max_tts_phrases=max_tts_phrases,
            full_voice_mode=full_voice_mode,
            speech_coverage_sink=speech_coverage_sink,
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
    max_tts_phrases: int | None,
    full_voice_mode: bool,
    speech_coverage_sink: SpeechCoverageSink | None,
) -> ChatResponse:
    context_started = perf_counter()
    active_session = await memory.session_id(session_id)
    await memory.add(active_session, Message(role="user", content=text))
    messages = context.build_messages(await memory.get_history(active_session))
    context_chars = sum(len(message["content"]) for message in messages)
    trace.mark(
        "llm_context_prepared",
        duration_seconds=perf_counter() - context_started,
        message_count=len(messages),
        context_chars=context_chars,
        estimated_input_tokens=(context_chars + 3) // 4,
    )
    started = perf_counter()
    trace.mark("llm_stream_request_start")
    reply_parts: list[str] = []
    sentence_buffer = ""
    audio_queue: asyncio.Queue[tuple[str, int] | None] | None = None
    tts_worker: asyncio.Task[None] | None = None
    chunk_index = 0
    phrases_queued = 0
    first_tts_chunk_sent = False
    pending_tail_buffer = ""
    pending_tail_overflow = False
    tail_started = False
    speech_coverage_issue: str | None = None
    speech_segments_delivered = 0

    def remember_tail(part: str) -> None:
        nonlocal pending_tail_buffer, pending_tail_overflow
        if not full_voice_mode or not part.strip():
            return
        separator = " " if pending_tail_buffer else ""
        addition = separator + part.strip()
        remaining = BOUNDED_FULL_TTS_MAX_INPUT_CHARS + 1 - len(pending_tail_buffer)
        if remaining > 0:
            pending_tail_buffer += addition[:remaining]
        if len(addition) > remaining:
            pending_tail_overflow = True

    async def queue_phrase(sentence: str) -> bool:
        nonlocal chunk_index, phrases_queued, speech_coverage_issue
        assert audio_queue is not None
        if full_voice_mode and len(sentence) > BOUNDED_FULL_TTS_MAX_INPUT_CHARS:
            speech_coverage_issue = (
                f"a speech segment exceeded the local {BOUNDED_FULL_TTS_MAX_INPUT_CHARS}-character safety limit"
            )
            trace.mark(
                "tts_phrase_skipped_by_text_limit",
                chunk=chunk_index + 1,
                chars=len(sentence),
            )
            return False
        if max_tts_phrases is not None and phrases_queued >= max_tts_phrases:
            trace.mark(
                "tts_phrase_skipped_by_turn_limit",
                chunk=chunk_index + 1,
                words=_word_count(sentence),
            )
            if full_voice_mode:
                speech_coverage_issue = "the configured TTS request budget was exhausted"
            return False
        chunk_index += 1
        phrases_queued += 1
        trace.mark("tts_phrase_ready", chunk=chunk_index, words=_word_count(sentence))
        await audio_queue.put((sentence, chunk_index))
        return True

    async def synthesize_queued_audio() -> None:
        nonlocal chunk_index, speech_coverage_issue, speech_segments_delivered
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
                    speech_segments_delivered += 1
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
                    speech_segments_delivered += 1
                else:
                    # TTS is only needed when one of the client audio paths is active.
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception("TTS chunk delivery failed; continuing streamed text")
                if full_voice_mode and speech_coverage_issue is None:
                    speech_coverage_issue = (
                        f"audio segment {current_chunk} failed ({type(error).__name__})"
                    )

    if audio_sink is not None or audio_stream_sink is not None:
        audio_queue = asyncio.Queue(maxsize=2)
        tts_worker = asyncio.create_task(synthesize_queued_audio())

    try:
        async for token in ai.stream_reply(messages):
            reply_parts.append(token)
            sentence_buffer += token
            await token_sink(token, active_session)
            if audio_queue is not None:
                chunks: list[str] = []
                if full_voice_mode and tail_started:
                    remember_tail(sentence_buffer)
                    sentence_buffer = ""
                else:
                    chunks, sentence_buffer = take_tts_chunks(
                        sentence_buffer,
                        allow_short_first_chunk=not first_tts_chunk_sent,
                        first_chunk_max_words=first_chunk_max_words,
                    )
                    for chunk in chunks:
                        if full_voice_mode:
                            if (
                                tail_started
                                or phrases_queued >= 2
                                or len(chunk) > BOUNDED_FULL_TTS_MAX_INPUT_CHARS
                            ):
                                tail_started = True
                                remember_tail(chunk)
                            elif not await queue_phrase(chunk):
                                tail_started = True
                                remember_tail(chunk)
                        else:
                            await queue_phrase(chunk)
                first_tts_chunk_sent = first_tts_chunk_sent or bool(chunks)
        if audio_queue is not None:
            if full_voice_mode:
                remember_tail(sentence_buffer)
                tail = pending_tail_buffer
                if tail:
                    tail_prefix = _bounded_speech_prefix(
                        tail, BOUNDED_FULL_TTS_MAX_INPUT_CHARS
                    )
                    if pending_tail_overflow or len(tail_prefix) < len(tail):
                        speech_coverage_issue = (
                            "the remaining reply exceeded the local TTS text limit; only its safe prefix was queued"
                        )
                    if tail_prefix:
                        await queue_phrase(tail_prefix)
                    elif speech_coverage_issue is None:
                        speech_coverage_issue = (
                            "the remaining reply could not be split safely under the local TTS text limit"
                        )
            elif sentence_buffer.strip():
                await queue_phrase(sentence_buffer.strip())
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
    if full_voice_mode:
        coverage_complete = speech_coverage_issue is None
        coverage_message = (
            "Full-reply audio was sent to the browser. This confirms delivery, not audible playback."
            if coverage_complete
            else f"The full reply text is available, but audio coverage is incomplete: {speech_coverage_issue}."
        )
        trace.mark(
            "speech_coverage_reported",
            complete=coverage_complete,
            segments_delivered=speech_segments_delivered,
            reason=speech_coverage_issue,
        )
        if speech_coverage_sink is not None:
            await speech_coverage_sink(coverage_complete, coverage_message)
    trace.mark("voice_generation_complete")
    return result
