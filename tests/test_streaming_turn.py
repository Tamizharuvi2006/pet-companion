import asyncio
from collections.abc import AsyncIterator

from app.memory.short_term import ShortTermMemory
from app.services.context_service import ContextService
from app.services.streaming_turn_service import stream_turn
from app.services.tts_service import TTSAudioChunk


class FakeAI:
    def __init__(self, audio_started: asyncio.Event, events: list[str]) -> None:
        self.audio_started = audio_started
        self.events = events

    async def stream_reply(self, _messages: list[dict[str, str]]) -> AsyncIterator[str]:
        assert "put the useful answer in the opening sentence" in _messages[0]["content"]
        for token in ("one ", "two ", "three ", "four. "):
            yield token
        # The model must be able to continue only after the TTS worker has
        # actually produced audio from the initial phrase.
        await asyncio.wait_for(self.audio_started.wait(), timeout=0.5)
        self.events.append("llm_continued")
        yield "five six seven eight nine ten."


class FakeTTS:
    async def synthesize(self, _text: str) -> str:
        raise AssertionError("Streaming path should not create a complete file")

    async def stream_audio(self, _text: str) -> AsyncIterator[TTSAudioChunk]:
        yield TTSAudioChunk(provider="test", data=b"first-audio-bytes")


def test_unpunctuated_opening_starts_tts_before_llm_finishes():
    async def run():
        started = asyncio.Event()
        phrases = []

        class AI:
            async def stream_reply(self, messages):
                for token in ("Hey ", "macha ", "I ", "am ", "doing ", "great "):
                    yield token
                await asyncio.wait_for(started.wait(), 0.5)
                yield "and happy to hear from you."

        class TTS(FakeTTS):
            async def stream_audio(self, text):
                phrases.append(text)
                started.set()
                yield TTSAudioChunk(provider="test", data=b"audio")

        async def tokens(*args):
            pass

        async def audio(chunks, index):
            async for piece in chunks:
                pass

        result = await stream_turn(text="hi", session_id=None,
            memory=ShortTermMemory(), context=ContextService(), ai=AI(), tts=TTS(),
            token_sink=tokens, audio_sink=None, audio_stream_sink=audio,
            first_chunk_max_words=6)
        assert phrases == ["Hey macha I am doing great", "and happy to hear from you."]
        assert result.reply == " ".join(phrases)

    asyncio.run(run())


def test_tiny_opener_and_short_tail_use_one_tts_request() -> None:
    class ShortAI:
        async def stream_reply(self, _messages):
            yield "Hello there! "
            await asyncio.sleep(0.02)
            yield "You look happy today."

    async def run():
        calls = []

        class TTS(FakeTTS):
            async def stream_audio(self, text):
                calls.append(text)
                yield TTSAudioChunk(provider="test", data=b"audio")

        async def tokens(*args):
            pass

        async def audio(chunks, index):
            async for chunk in chunks:
                pass

        result = await stream_turn(
            text="hello", session_id=None, memory=ShortTermMemory(),
            context=ContextService(), ai=ShortAI(), tts=TTS(),
            token_sink=tokens, audio_sink=None, audio_stream_sink=audio,
        )
        assert calls == ["Hello there! You look happy today."]
        assert result.reply == calls[0]

    asyncio.run(run())


def test_first_audio_is_delivered_while_llm_is_still_streaming() -> None:
    async def run() -> None:
        audio_started = asyncio.Event()
        events: list[str] = []
        received_audio: list[bytes] = []

        async def token_sink(_token: str, _session_id: str) -> None:
            await asyncio.sleep(0)

        async def audio_sink(
            chunks: AsyncIterator[TTSAudioChunk], _chunk_index: int
        ) -> None:
            async for piece in chunks:
                events.append("audio")
                received_audio.append(piece.data)
                audio_started.set()

        result = await stream_turn(
            text="test prompt",
            session_id=None,
            memory=ShortTermMemory(),
            context=ContextService(),
            ai=FakeAI(audio_started, events),  # type: ignore[arg-type]
            tts=FakeTTS(),  # type: ignore[arg-type]
            token_sink=token_sink,
            audio_sink=None,
            audio_stream_sink=audio_sink,
            first_chunk_max_words=4,
        )

        assert result.reply == "one two three four. five six seven eight nine ten."
        assert events.index("audio") < events.index("llm_continued")
        assert len(received_audio) == 2

    asyncio.run(run())


def test_voice_prompt_does_not_change_text_chat_prompt() -> None:
    context = ContextService()
    assert context.build_messages([])[0]["content"] == context.system_prompt


def test_first_phrase_only_mode_keeps_full_text_but_synthesizes_once() -> None:
    class MultiPhraseAI:
        async def stream_reply(self, _messages: list[dict[str, str]]) -> AsyncIterator[str]:
            yield "Hello there. "
            yield "The second sentence remains visible as text only."

    class CountingTTS:
        def __init__(self) -> None:
            self.requests: list[str] = []

        async def synthesize(self, _text: str) -> str:
            raise AssertionError("Streaming mode should not use complete-file TTS")

        async def stream_audio(self, text: str) -> AsyncIterator[TTSAudioChunk]:
            self.requests.append(text)
            yield TTSAudioChunk(provider="test", data=b"mp3-frame")

    async def run() -> None:
        tts = CountingTTS()
        replies: list[str] = []
        spoken: list[tuple[int, bytes]] = []

        async def token_sink(token: str, _session_id: str) -> None:
            replies.append(token)

        async def audio_sink(
            chunks: AsyncIterator[TTSAudioChunk], chunk_index: int
        ) -> None:
            async for piece in chunks:
                spoken.append((chunk_index, piece.data))

        result = await stream_turn(
            text="test prompt",
            session_id=None,
            memory=ShortTermMemory(),
            context=ContextService(),
            ai=MultiPhraseAI(),  # type: ignore[arg-type]
            tts=tts,  # type: ignore[arg-type]
            token_sink=token_sink,
            audio_sink=None,
            audio_stream_sink=audio_sink,
            first_chunk_max_words=6,
            max_tts_phrases=1,
        )

        assert result.reply == "Hello there. The second sentence remains visible as text only."
        assert "".join(replies) == result.reply
        assert tts.requests == ["Hello there."]
        assert spoken == [(1, b"mp3-frame")]

    asyncio.run(run())
