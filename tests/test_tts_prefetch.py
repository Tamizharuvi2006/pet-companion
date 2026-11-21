import asyncio
import pytest

from app.memory.short_term import ShortTermMemory
from app.services.context_service import ContextService
from app.services.streaming_turn_service import stream_turn
from app.services.tts_service import TTSAudioChunk


class Reply:
    def __init__(self, tail="five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen."):
        self.tail = tail

    async def stream_reply(self, messages):
        yield "One two three four. "
        yield self.tail


@pytest.mark.parametrize("tail", ["Just four more words.", "five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen."])
def test_prefetch_overlaps_but_delivery_stays_ordered(tail):
    async def run():
        second_started = asyncio.Event()
        delivered = []

        class TTS:
            async def stream_audio(self, text):
                if text.startswith("One"):
                    await asyncio.wait_for(second_started.wait(), 0.5)
                    yield TTSAudioChunk("test", b"first")
                else:
                    second_started.set()
                    yield TTSAudioChunk("test", b"second")

        async def tokens(*args):
            pass

        async def audio(chunks, index):
            async for chunk in chunks:
                delivered.append((index, chunk.data))

        await stream_turn(text="test", session_id=None, memory=ShortTermMemory(),
                          context=ContextService(), ai=Reply(tail), tts=TTS(),
                          token_sink=tokens, audio_sink=None, audio_stream_sink=audio,
                          first_chunk_max_words=4)
        assert delivered == [(1, b"first"), (2, b"second")]

    asyncio.run(run())


def test_cancel_closes_first_and_prefetched_provider_streams():
    async def run():
        opened = set()
        closed = set()
        both_open = asyncio.Event()

        class TTS:
            async def stream_audio(self, text):
                key = text.startswith("One")
                opened.add(key)
                if len(opened) == 2:
                    both_open.set()
                try:
                    await asyncio.Event().wait()
                    yield TTSAudioChunk("test", b"unused")
                finally:
                    closed.add(key)

        async def tokens(*args):
            pass

        async def audio(chunks, index):
            async for chunk in chunks:
                pass

        task = asyncio.create_task(stream_turn(
            text="test", session_id=None, memory=ShortTermMemory(),
            context=ContextService(), ai=Reply(), tts=TTS(),
            token_sink=tokens, audio_sink=None, audio_stream_sink=audio,
            first_chunk_max_words=4))
        await asyncio.wait_for(both_open.wait(), 0.5)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert opened == closed == {True, False}

    asyncio.run(run())
