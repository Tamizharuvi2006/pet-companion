import asyncio
from types import SimpleNamespace

from app.core.config import Settings
from app.memory.short_term import ShortTermMemory
from app.services.context_service import ContextService
from app.services.voice_trace import VoiceTrace
from app.api.websocket import _handle_text


def test_audio_mini_browser_turn_streams_pcm_without_starting_kokoro():
    async def run() -> None:
        sent: list[tuple[str, object]] = []

        class FakeSocket:
            def __init__(self) -> None:
                self.app = SimpleNamespace(state=SimpleNamespace(
                    settings=Settings(tts_first_chunk_words=5),
                    memory=ShortTermMemory(),
                    context=ContextService(),
                    tts=object(),
                ))

            async def send_json(self, payload) -> None:
                sent.append(("json", payload))

            async def send_bytes(self, payload: bytes) -> None:
                sent.append(("bytes", payload))

        class FakeTurn:
            def __init__(self, audio_sink) -> None:
                self.audio_sink = audio_sink

            async def stream_reply(self, messages):
                assert "put the useful answer in the opening sentence" in messages[0]["content"]
                assert messages[-1] == {"role": "user", "content": "Hello Bella"}
                yield "Hey there."
                await self.audio_sink(b"\x00\x00")

        class FakeAudioMini:
            def create_turn(self, **kwargs):
                return FakeTurn(kwargs["audio_sink"])

        socket = FakeSocket()
        socket.app.state.openrouter_audio_mini = FakeAudioMini()
        result = await _handle_text(
            socket,
            "Hello Bella",
            None,
            voice_trace=VoiceTrace(),
            voice_engine="gpt_audio_mini",
        )
        json_events = [payload for kind, payload in sent if kind == "json"]
        event_types = [payload["type"] for payload in json_events]
        assert result.reply == "Hey there."
        assert event_types.index("pcm_stream_start") < event_types.index("reply_delta")
        assert event_types.index("pcm_stream_end") < event_types.index("reply")
        assert any(kind == "bytes" and value == b"\x00\x00" for kind, value in sent)

    asyncio.run(run())
