from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TTSAudioChunk:
    """An incremental MP3 byte piece emitted by a TTS provider."""

    provider: str
    data: bytes


class TTSService(Protocol):
    """Common interface for Bella's selectable speech providers."""

    async def load(self) -> None:
        """Prepare the provider once during application startup."""

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> str:
        """Create an audio file and return its public application URL."""

    def stream_audio(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Yield encoded audio as soon as the provider makes bytes available."""

    async def close(self) -> None:
        """Release provider resources during shutdown."""
