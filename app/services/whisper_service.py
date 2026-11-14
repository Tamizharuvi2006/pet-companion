import asyncio
import logging
import time
from pathlib import Path

from app.core.config import Settings

logger = logging.getLogger(__name__)


class WhisperService:
    """Preloaded tiny-interim/base-final Faster-Whisper adapter."""

    def __init__(self, settings: Settings) -> None:
        self._final_model_name = settings.whisper_model
        self._interim_model_name = settings.whisper_interim_model
        self._device = settings.whisper_device
        self._language = settings.whisper_language
        self._final_beam_size = settings.whisper_final_beam_size
        self._interim_beam_size = settings.whisper_interim_beam_size
        self._models: dict[str, object] = {}
        self._model_locks: dict[str, asyncio.Lock] = {}
        self._transcription_locks: dict[str, asyncio.Lock] = {}

    async def load(self) -> None:
        """Load each configured model once during application startup."""
        for model_name in dict.fromkeys((self._interim_model_name, self._final_model_name)):
            await self._get_model(model_name)

    async def transcribe(self, audio_path: Path, *, interim: bool = False) -> str:
        model_name = self._interim_model_name if interim else self._final_model_name
        beam_size = self._interim_beam_size if interim else self._final_beam_size
        model = await self._get_model(model_name)
        start = time.time()
        try:
            async with self._transcription_locks[model_name]:
                text = await asyncio.to_thread(self._transcribe_file, model, audio_path, beam_size)
            label = f"Whisper interim ({model_name}) time" if interim else f"Whisper final ({model_name}) time"
            logger.info("%s: %.2fs", label, time.time() - start)
            if not text:
                raise RuntimeError("No speech was detected in the audio")
            return text
        except RuntimeError:
            raise
        except Exception as error:
            if interim:
                # A live WebM fragment is not always independently decodable.
                # Missing interim text is expected; the final recording remains
                # the authoritative transcription input.
                logger.debug("Interim transcription skipped: %s", error)
            else:
                logger.exception("Transcription failed")
            raise RuntimeError("Could not transcribe this audio") from error

    def _transcribe_file(self, model: object, audio_path: Path, beam_size: int) -> str:
        segments, _ = model.transcribe(
            str(audio_path),
            vad_filter=True,
            beam_size=beam_size,
            language=self._language,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    async def _get_model(self, model_name: str) -> object:
        if model_name not in self._models:
            lock = self._model_locks.setdefault(model_name, asyncio.Lock())
            async with lock:
                if model_name not in self._models:
                    from faster_whisper import WhisperModel

                    logger.info(
                        "Loading Faster-Whisper model: %s on %s", model_name, self._device
                    )
                    self._models[model_name] = await asyncio.to_thread(
                        WhisperModel, model_name, device=self._device, compute_type="int8"
                    )
                    self._transcription_locks[model_name] = asyncio.Lock()
        return self._models[model_name]
