import asyncio
from collections.abc import AsyncIterator
from time import perf_counter

from app.memory.short_term import ShortTermMemory
from app.services.context_service import ContextService
from app.services.streaming_turn_service import stream_turn
from app.services.tts_service import TTSAudioChunk


class DelayedFirstTokenAI:
    def __init__(self, first_token_delay: float, continuation_delay: float) -> None:
        self.first_token_delay = first_token_delay
        self.continuation_delay = continuation_delay
        self.completed_at: float | None = None

    async def stream_reply(self, _messages: list[dict[str, str]]) -> AsyncIterator[str]:
        await asyncio.sleep(self.first_token_delay)
        yield "Hello there. "
        await asyncio.sleep(self.continuation_delay)
        self.completed_at = perf_counter()
        yield "The rest stays visible as text."


class DelayedFirstAudioTTS:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.requests: list[str] = []

    async def synthesize(self, _text: str) -> str:
        raise AssertionError("Streaming test should not synthesize complete files")

    async def stream_audio(self, text: str) -> AsyncIterator[TTSAudioChunk]:
        self.requests.append(text)
        await asyncio.sleep(self.delay)
        yield TTSAudioChunk(provider="offline-fake", data=b"first-frame")


async def run_scaled_voice_pipeline() -> dict[str, float]:
    # 1/100 scale of the observed 2.0 s / 4.6 s / 1.3 s provider stages.
    stt_delay, gpt_ttft, tts_prefix = 0.020, 0.046, 0.013
    turn_started = perf_counter()
    await asyncio.sleep(stt_delay)
    stt_complete = perf_counter()
    ai = DelayedFirstTokenAI(gpt_ttft, continuation_delay=0.080)
    tts = DelayedFirstAudioTTS(tts_prefix)
    first_audio_at: float | None = None
    first_text_at: float | None = None

    async def token_sink(_token: str, _session_id: str) -> None:
        nonlocal first_text_at
        first_text_at = first_text_at or perf_counter()

    async def audio_sink(
        chunks: AsyncIterator[TTSAudioChunk], _chunk_index: int
    ) -> None:
        nonlocal first_audio_at
        async for _piece in chunks:
            first_audio_at = first_audio_at or perf_counter()

    result = await stream_turn(
        text="synthetic transcript",
        session_id=None,
        memory=ShortTermMemory(),
        context=ContextService(),
        ai=ai,  # type: ignore[arg-type]
        tts=tts,  # type: ignore[arg-type]
        token_sink=token_sink,
        audio_sink=None,
        audio_stream_sink=audio_sink,
        max_tts_phrases=1,
    )
    completed_at = perf_counter()

    assert result.reply == "Hello there. The rest stays visible as text."
    assert first_text_at is not None and first_audio_at is not None
    assert ai.completed_at is not None
    assert first_audio_at < ai.completed_at
    assert len(tts.requests) == 1
    return {
        "stt_ms": (stt_complete - turn_started) * 1000,
        "gpt_ttft_ms": (first_text_at - stt_complete) * 1000,
        "tts_first_audio_ms": (first_audio_at - first_text_at) * 1000,
        "record_stop_to_first_audio_ms": (first_audio_at - turn_started) * 1000,
        "first_audio_before_llm_complete_ms": (ai.completed_at - first_audio_at) * 1000,
        "turn_complete_ms": (completed_at - turn_started) * 1000,
    }


def test_scenario_a_scaled_stt_gpt_tts_and_scenario_c_overlap() -> None:
    measurements = asyncio.run(run_scaled_voice_pipeline())
    assert measurements["stt_ms"] >= 16
    assert measurements["gpt_ttft_ms"] >= 36.8
    assert measurements["tts_first_audio_ms"] >= 6.5
    assert measurements["first_audio_before_llm_complete_ms"] > 0


def test_scenario_g_midstream_audio_failure_does_not_retry_tts() -> None:
    class OnePhraseAI:
        async def stream_reply(self, _messages: list[dict[str, str]]) -> AsyncIterator[str]:
            yield "Hello there."

    class TruncatedTTS:
        def __init__(self) -> None:
            self.requests = 0

        async def synthesize(self, _text: str) -> str:
            raise AssertionError("Streaming test should not use complete files")

        async def stream_audio(self, _text: str) -> AsyncIterator[TTSAudioChunk]:
            self.requests += 1
            yield TTSAudioChunk(provider="fake", data=b"initial-audio")
            raise RuntimeError("simulated failure after first audio")

    async def run() -> None:
        tts = TruncatedTTS()
        delivered: list[bytes] = []

        async def audio_sink(
            chunks: AsyncIterator[TTSAudioChunk], _chunk_index: int
        ) -> None:
            async for chunk in chunks:
                delivered.append(chunk.data)
                raise RuntimeError("simulated client-side stream failure")

        result = await stream_turn(
            text="test",
            session_id=None,
            memory=ShortTermMemory(),
            context=ContextService(),
            ai=OnePhraseAI(),  # type: ignore[arg-type]
            tts=tts,  # type: ignore[arg-type]
            token_sink=lambda *_args: asyncio.sleep(0),
            audio_sink=None,
            audio_stream_sink=audio_sink,
            max_tts_phrases=1,
        )
        assert result.reply == "Hello there."
        assert delivered == [b"initial-audio"]
        assert tts.requests == 1

    asyncio.run(run())
