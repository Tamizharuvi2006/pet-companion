import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from app.device.audio_bridge import stream_mp3_chunks_as_pcm
from app.device.protocol import AUDIO_HEADER, AUDIO_HEADER_BYTES, AUDIO_TYPE_SPEAKER
from app.services.tts_service import TTSAudioChunk
from app.services.mp3_stream import has_complete_mp3_frames


class FakeWebSocket:
    def __init__(self, input_complete: list[bool]) -> None:
        self.input_complete = input_complete
        self.messages: list[dict[str, object] | bytes] = []
        self.first_pcm_before_input_complete = False

    async def send_json(self, payload: dict[str, object]) -> None:
        self.messages.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        if not self.first_pcm_before_input_complete:
            self.first_pcm_before_input_complete = not self.input_complete[0]
        self.messages.append(payload)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_device_audio_is_decoded_and_forwarded_before_mp3_finishes(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "sample.mp3"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=880:duration=1.5",
                "-ac", "1", "-ar", "16000", "-b:a", "32k", str(source),
            ],
            check=True,
            capture_output=True,
        )
        mp3 = source.read_bytes()
        assert has_complete_mp3_frames(mp3)
        input_complete = [False]
        websocket = FakeWebSocket(input_complete)

        async def encoded_chunks():
            for offset in range(0, len(mp3), 256):
                yield TTSAudioChunk(provider="test", data=mp3[offset : offset + 256])
                await asyncio.sleep(0.02)
            input_complete[0] = True

        total_pcm = await stream_mp3_chunks_as_pcm(
            websocket,  # type: ignore[arg-type]
            encoded_chunks(),
            turn_id=7,
            chunk_id=1,
            trace_id="testtrace123",
            max_frame_bytes=2048,
            send_lock=asyncio.Lock(),
        )

        controls = [message for message in websocket.messages if isinstance(message, dict)]
        binary_frames = [message for message in websocket.messages if isinstance(message, bytes)]
        assert controls[0]["type"] == "tts_chunk_start"
        assert controls[-1]["type"] == "tts_chunk_end"
        assert binary_frames
        assert websocket.first_pcm_before_input_complete
        parsed_frames = [AUDIO_HEADER.unpack_from(frame) for frame in binary_frames]
        payloads = [frame[AUDIO_HEADER_BYTES:] for frame in binary_frames]
        assert all(header[0] == AUDIO_TYPE_SPEAKER for header in parsed_frames)
        assert [header[4] for header in parsed_frames] == list(range(len(binary_frames)))
        assert total_pcm == sum(len(payload) for payload in payloads)
        assert all(len(payload) % 2 == 0 for payload in payloads)

    asyncio.run(run())
