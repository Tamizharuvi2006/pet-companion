import asyncio
import logging
import threading
from pathlib import Path
from time import perf_counter

from app.core.config import Settings

logger = logging.getLogger(__name__)


class WhisperService:
    """Preloaded tiny-interim/base-final Faster-Whisper adapter."""

    def __init__(self, settings: Settings) -> None:
        self._final_model_name = settings.whisper_model
        self._interim_model_name = settings.whisper_interim_model
        self._interim_enabled = settings.whisper_interim_enabled
        self._device = settings.whisper_device
        self._language = settings.whisper_language
        self._final_beam_size = settings.whisper_final_beam_size
        self._interim_beam_size = settings.whisper_interim_beam_size
        self._models: dict[str, object] = {}
        self._model_locks: dict[str, asyncio.Lock] = {}
        self._transcription_locks: dict[str, asyncio.Lock] = {}
        self._thread_transcription_locks: dict[str, threading.Lock] = {}
        self._worker_stats_lock = threading.Lock()
        self._active_interim_workers = 0

    async def load(self) -> None:
        """Load each configured model once during application startup."""
        for model_name in self._configured_model_names():
            await self._get_model(model_name)

    def _configured_model_names(self) -> tuple[str, ...]:
        configured_models = (
            (self._interim_model_name, self._final_model_name)
            if self._interim_enabled
            else (self._final_model_name,)
        )
        return tuple(dict.fromkeys(configured_models))

    async def transcribe(self, audio_path: Path, *, interim: bool = False) -> str:
        if interim and not self._interim_enabled:
            return ""
        model_name = self._interim_model_name if interim else self._final_model_name
        beam_size = self._interim_beam_size if interim else self._final_beam_size
        model = await self._get_model(model_name)
        start = perf_counter()
        try:
            async with self._transcription_locks[model_name]:
                text = await asyncio.to_thread(
                    self._transcribe_file,
                    model,
                    audio_path,
                    beam_size,
                    model_name,
                    interim,
                )
            label = f"Whisper interim ({model_name}) time" if interim else f"Whisper final ({model_name}) time"
            logger.info("%s: %.2fs", label, perf_counter() - start)
            if not text:
                raise RuntimeError("No speech was detected in the audio")
            return text
        except asyncio.CancelledError:
            if interim:
                logger.info(
                    "Whisper interim waiter cancelled; worker thread may continue (model=%s active=%s)",
                    model_name,
                    self._active_interim_worker_count(),
                )
            raise
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

    def _transcribe_file(
        self,
        model: object,
        audio_path: Path,
        beam_size: int,
        model_name: str,
        interim: bool,
    ) -> str:
        """Run decode off-loop and hold a thread lock even if its waiter is cancelled."""
        thread_lock = self._thread_transcription_locks[model_name]
        with thread_lock:
            if interim:
                with self._worker_stats_lock:
                    self._active_interim_workers += 1
                    active = self._active_interim_workers
                logger.info("whisper_interim_worker_started model=%s active=%s", model_name, active)
            started = perf_counter()
            try:
                segments, _ = model.transcribe(
                    str(audio_path),
                    vad_filter=True,
                    beam_size=beam_size,
                    language=self._language,
                )
                return " ".join(segment.text.strip() for segment in segments).strip()
            finally:
                if interim:
                    with self._worker_stats_lock:
                        self._active_interim_workers -= 1
                        active = self._active_interim_workers
                    logger.info(
                        "whisper_interim_worker_finished model=%s active=%s duration_ms=%.1f",
                        model_name,
                        active,
                        (perf_counter() - started) * 1000,
                    )

    def _active_interim_worker_count(self) -> int:
        with self._worker_stats_lock:
            return self._active_interim_workers

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
                    self._thread_transcription_locks[model_name] = threading.Lock()
        return self._models[model_name]
