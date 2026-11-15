import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.openrouter_stt_service import OpenRouterSTTService
from app.services.whisper_service import WhisperService


def test_disabling_interim_skips_tiny_model_load_and_inference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def run() -> None:
        service = WhisperService(
            Settings(
                whisper_model="base",
                whisper_interim_model="tiny",
                whisper_interim_enabled=False,
            )
        )
        assert service._configured_model_names() == ("base",)
        not_loaded: list[str] = []

        async def fake_get_model(model_name: str) -> object:
            not_loaded.append(model_name)
            return object()

        monkeypatch.setattr(service, "_get_model", fake_get_model)
        assert await service.transcribe(tmp_path / "unused.webm", interim=True) == ""
        assert not_loaded == []

    asyncio.run(run())


def test_disabling_interim_keeps_final_stt_adapter_but_skips_partial_calls(
    tmp_path: Path,
) -> None:
    class NoLocalPartial:
        async def transcribe(self, _path: Path, *, interim: bool = False) -> str:
            raise AssertionError("Disabled interim must not call local Whisper")

    async def run() -> None:
        settings = Settings(whisper_interim_enabled=False)
        service = OpenRouterSTTService(settings, NoLocalPartial())  # type: ignore[arg-type]
        assert await service.transcribe(tmp_path / "unused.webm", interim=True) == ""
        await service.close()

    asyncio.run(run())


def test_cancelled_interim_waiter_does_not_claim_thread_stopped(tmp_path: Path) -> None:
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    finished = threading.Event()
    stats_lock = threading.Lock()
    stats = {"calls": 0, "active": 0, "max_active": 0}

    class BlockingModel:
        def transcribe(self, *_args: object, **_kwargs: object):
            with stats_lock:
                stats["calls"] += 1
                call_number = stats["calls"]
                stats["active"] += 1
                stats["max_active"] = max(stats["max_active"], stats["active"])
            if call_number == 1:
                first_started.set()
            else:
                second_started.set()
            try:
                if call_number == 1:
                    release_first.wait(timeout=2)
                return iter([SimpleNamespace(text="partial words")]), None
            finally:
                with stats_lock:
                    stats["active"] -= 1
                if call_number == 2:
                    finished.set()

    async def run() -> None:
        service = WhisperService(Settings(whisper_interim_enabled=True))
        service._models["tiny"] = BlockingModel()
        service._transcription_locks["tiny"] = asyncio.Lock()
        service._thread_transcription_locks["tiny"] = threading.Lock()
        audio = tmp_path / "partial.webm"
        audio.write_bytes(b"fake")

        waiter = asyncio.create_task(service.transcribe(audio, interim=True))
        assert await asyncio.to_thread(first_started.wait, 1.0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert service._active_interim_worker_count() == 1

        second_waiter = asyncio.create_task(service.transcribe(audio, interim=True))
        await asyncio.sleep(0.03)
        assert not second_started.is_set()
        assert stats["max_active"] == 1

        release_first.set()
        assert await asyncio.to_thread(finished.wait, 1.0)
        assert await second_waiter == "partial words"
        assert service._active_interim_worker_count() == 0
        assert stats["max_active"] == 1

    asyncio.run(run())
