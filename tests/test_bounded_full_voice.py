import asyncio
import re
from collections.abc import AsyncIterator

import pytest

from app.core.config import Settings, get_settings
from app.memory.short_term import ShortTermMemory
from app.services.context_service import ContextService
from app.services.provider_budget import BOUNDED_FULL_TTS_MAX_INPUT_CHARS
from app.services.streaming_turn_service import stream_turn
from app.services.tts_service import TTSAudioChunk


class PhraseAI:
    def __init__(self, phrases: list[str], first_audio: asyncio.Event | None = None) -> None:
        self.phrases = phrases
        self.first_audio = first_audio
        self.continued_after_first_audio = False

    async def stream_reply(self, _messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if not self.phrases:
            return
        yield self.phrases[0]
        if self.first_audio is not None and len(self.phrases) > 1:
            await asyncio.wait_for(self.first_audio.wait(), timeout=1.0)
            self.continued_after_first_audio = True
        for phrase in self.phrases[1:]:
            yield f" {phrase}"


class CapturingTTS:
    def __init__(self) -> None:
        self.requests: list[str] = []

    async def synthesize(self, _text: str) -> str:
        raise AssertionError("Full-voice streaming should not create complete files")

    async def stream_audio(self, text: str) -> AsyncIterator[TTSAudioChunk]:
        self.requests.append(text)
        yield TTSAudioChunk(provider="offline-fixture", data=b"synthetic-valid-audio")


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


async def _run_full_voice(phrases: list[str]) -> tuple[str, CapturingTTS, list[tuple[int, bytes]], list[tuple[bool, str]], PhraseAI]:
    first_audio = asyncio.Event()
    ai = PhraseAI(phrases, first_audio)
    tts = CapturingTTS()
    reply_deltas: list[str] = []
    audio_segments: list[tuple[int, bytes]] = []
    coverage: list[tuple[bool, str]] = []

    async def token_sink(token: str, _session_id: str) -> None:
        reply_deltas.append(token)

    async def audio_sink(
        chunks: AsyncIterator[TTSAudioChunk], chunk_index: int
    ) -> None:
        async for chunk in chunks:
            audio_segments.append((chunk_index, chunk.data))
            first_audio.set()

    async def coverage_sink(complete: bool, message: str) -> None:
        coverage.append((complete, message))

    result = await stream_turn(
        text="offline user prompt",
        session_id=None,
        memory=ShortTermMemory(),
        context=ContextService(),
        ai=ai,  # type: ignore[arg-type]
        tts=tts,  # type: ignore[arg-type]
        token_sink=token_sink,
        audio_sink=None,
        audio_stream_sink=audio_sink,
        max_tts_phrases=3,
        full_voice_mode=True,
        speech_coverage_sink=coverage_sink,
    )
    assert "".join(reply_deltas).strip() == result.reply
    return result.reply, tts, audio_segments, coverage, ai


@pytest.mark.parametrize(
    ("phrases", "expected_segments"),
    [
        (["Hello there, sweet friend!"], 1),
        (["Hello there, sweet friend!", "I am glad you came."], 2),
        (
            [
                "Hello there, sweet friend!",
                "This second phrase has fifteen nice words for a calm and natural speech segment today.",
                "A third phrase keeps Bella speaking smoothly while the remaining reply arrives from GPT.",
            ],
            3,
        ),
        (
            [
                "Hello there, sweet friend!",
                "This second phrase has fifteen nice words for a calm and natural speech segment today.",
                "A third phrase keeps Bella speaking smoothly while the remaining reply arrives from GPT.",
                "A fourth phrase must join the final segment without losing words or changing their order.",
            ],
            3,
        ),
        (["Hey."], 1),
    ],
)
def test_full_voice_speaks_each_word_once_in_order_with_at_most_three_segments(
    phrases: list[str], expected_segments: int
) -> None:
    reply, tts, audio_segments, coverage, ai = asyncio.run(_run_full_voice(phrases))
    assert len(tts.requests) == expected_segments <= 3
    assert [index for index, _data in audio_segments] == list(range(1, expected_segments + 1))
    assert _words(" ".join(tts.requests)) == _words(reply)
    assert coverage and coverage[-1][0] is True
    if len(phrases) > 1:
        assert ai.continued_after_first_audio


def test_full_voice_caps_oversized_tail_and_explicitly_reports_incomplete_audio() -> None:
    async def run() -> None:
        phrases = [
            "Hello there, sweet friend!",
            "This second phrase has fifteen nice words for a calm and natural speech segment today.",
            " ".join(["tailword"] * 700) + ".",
        ]
        reply, tts, _audio, coverage, _ai = await _run_full_voice(phrases)
        assert len(reply) > BOUNDED_FULL_TTS_MAX_INPUT_CHARS
        assert len(tts.requests) == 3
        assert all(len(request) <= BOUNDED_FULL_TTS_MAX_INPUT_CHARS for request in tts.requests)
        assert coverage[-1][0] is False
        assert "audio coverage is incomplete" in coverage[-1][1]
        assert "tailword" in reply

    asyncio.run(run())


def test_kokoro_midstream_failure_reports_incomplete_without_retry() -> None:
    class FailingTTS(CapturingTTS):
        async def stream_audio(self, text: str) -> AsyncIterator[TTSAudioChunk]:
            self.requests.append(text)
            yield TTSAudioChunk(provider="offline-fixture", data=b"prefix-only")
            raise RuntimeError("synthetic truncation")

    async def run() -> None:
        tts = FailingTTS()
        coverage: list[tuple[bool, str]] = []

        async def audio_sink(chunks: AsyncIterator[TTSAudioChunk], _index: int) -> None:
            async for _chunk in chunks:
                pass

        await stream_turn(
            text="offline prompt",
            session_id=None,
            memory=ShortTermMemory(),
            context=ContextService(),
            ai=PhraseAI(["Hello there, sweet friend!"]),  # type: ignore[arg-type]
            tts=tts,  # type: ignore[arg-type]
            token_sink=lambda *_args: asyncio.sleep(0),
            audio_sink=None,
            audio_stream_sink=audio_sink,
            max_tts_phrases=3,
            full_voice_mode=True,
            speech_coverage_sink=lambda complete, message: _record_coverage(
                coverage, complete, message
            ),
        )
        assert len(tts.requests) == 1
        assert coverage and coverage[0][0] is False
        assert "RuntimeError" in coverage[0][1]

    asyncio.run(run())


async def _record_coverage(
    output: list[tuple[bool, str]], complete: bool, message: str
) -> None:
    output.append((complete, message))


def test_cancellation_during_tts_closes_stream_without_another_request() -> None:
    class BlockingTTS(CapturingTTS):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.closed = asyncio.Event()

        async def stream_audio(self, text: str) -> AsyncIterator[TTSAudioChunk]:
            self.requests.append(text)
            try:
                self.started.set()
                yield TTSAudioChunk(provider="offline-fixture", data=b"prefix")
                await asyncio.Event().wait()
            finally:
                self.closed.set()

    async def run() -> None:
        tts = BlockingTTS()

        async def audio_sink(chunks: AsyncIterator[TTSAudioChunk], _index: int) -> None:
            async for _chunk in chunks:
                pass

        task = asyncio.create_task(
            stream_turn(
                text="offline prompt",
                session_id=None,
                memory=ShortTermMemory(),
                context=ContextService(),
                ai=PhraseAI(["Hello there, sweet friend!"]),  # type: ignore[arg-type]
                tts=tts,  # type: ignore[arg-type]
                token_sink=lambda *_args: asyncio.sleep(0),
                audio_sink=None,
                audio_stream_sink=audio_sink,
                max_tts_phrases=3,
                full_voice_mode=True,
            )
        )
        await asyncio.wait_for(tts.started.wait(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert tts.closed.is_set()
        assert len(tts.requests) == 1

    asyncio.run(run())


def test_bounded_full_mode_is_explicit_and_mutually_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        openrouter_api_key="offline-only",
        bounded_full_voice_test=True,
        whisper_interim_enabled=False,
        tts_race_enabled=False,
    )
    assert settings.voice_test_enabled
    assert settings.voice_test_mode == "bounded_full_voice_test"
    settings.validate_voice_diagnostic()

    with pytest.raises(RuntimeError, match="Enable only one voice test mode"):
        Settings(
            openrouter_api_key="offline-only",
            voice_diagnostic_mode=True,
            bounded_full_voice_test=True,
        ).validate_voice_diagnostic()

    monkeypatch.setenv("BOUNDED_FULL_VOICE_TEST", "true")
    monkeypatch.setenv("VOICE_DIAGNOSTIC_MODE", "false")
    get_settings.cache_clear()
    try:
        loaded = get_settings()
        assert loaded.bounded_full_voice_test is True
        assert loaded.voice_diagnostic_mode is False
    finally:
        get_settings.cache_clear()
