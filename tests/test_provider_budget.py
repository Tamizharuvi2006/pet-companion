import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.services import ai_service as ai_service_module
from app.services.ai_service import AIService
from app.services.edge_tts_service import EdgeTTSService
from app.services.openrouter_stt_service import OpenRouterSTTService
from app.services.openrouter_tts_service import OpenRouterTTSService
from app.services.provider_budget import (
    BOUNDED_FULL_TTS_MAX_INPUT_CHARS,
    ProviderBudgetError,
    provider_budget_scope,
    reserve_provider_call,
)
from app.services.tts_service import TTSAudioChunk
from app.services.whisper_service import WhisperService


def _valid_mp3() -> bytes:
    frame = b"\xff\xfb\x90\x64" + bytes(413)
    return frame + frame


def test_provider_budget_reservation_is_atomic_and_edge_is_zero() -> None:
    async def run() -> None:
        async with provider_budget_scope(True) as budget:
            assert budget is not None

            async def reserve_chat() -> str:
                try:
                    await reserve_provider_call("openrouter_chat", required=True)
                    return "reserved"
                except ProviderBudgetError:
                    return "denied"

            outcomes = await asyncio.gather(*(reserve_chat() for _ in range(20)))
            assert outcomes.count("reserved") == 1
            assert outcomes.count("denied") == 19
            with pytest.raises(ProviderBudgetError):
                await reserve_provider_call("edge_tts", required=True)
            snapshot = await budget.snapshot()
            assert snapshot["openrouter_chat"] == {"attempted": 1, "denied": 19, "limit": 1}
            assert snapshot["edge_tts"] == {"attempted": 0, "denied": 1, "limit": 0}

    asyncio.run(run())


def test_bounded_full_voice_budget_is_one_stt_one_chat_three_kokoro_zero_edge() -> None:
    async def run() -> None:
        async with provider_budget_scope("bounded_full_voice_test") as budget:
            assert budget is not None
            await reserve_provider_call("openrouter_stt", required=True)
            await reserve_provider_call("openrouter_chat", required=True)
            for _ in range(3):
                await reserve_provider_call("kokoro_tts", required=True)
            with pytest.raises(ProviderBudgetError):
                await reserve_provider_call("openrouter_stt", required=True)
            with pytest.raises(ProviderBudgetError):
                await reserve_provider_call("openrouter_chat", required=True)
            with pytest.raises(ProviderBudgetError):
                await reserve_provider_call("kokoro_tts", required=True)
            with pytest.raises(ProviderBudgetError):
                await reserve_provider_call("edge_tts", required=True)
            snapshot = await budget.snapshot()
            assert snapshot["openrouter_stt"] == {"attempted": 1, "denied": 1, "limit": 1}
            assert snapshot["openrouter_chat"] == {"attempted": 1, "denied": 1, "limit": 1}
            assert snapshot["kokoro_tts"] == {"attempted": 3, "denied": 1, "limit": 3}
            assert snapshot["edge_tts"] == {"attempted": 0, "denied": 1, "limit": 0}

    asyncio.run(run())


def test_diagnostic_settings_fail_closed_on_missing_key_or_model_change() -> None:
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        Settings(voice_diagnostic_mode=True).validate_voice_diagnostic()

    with pytest.raises(RuntimeError, match="WHISPER_INTERIM_ENABLED"):
        Settings(
            voice_diagnostic_mode=True,
            openrouter_api_key="test-only",
            tts_race_enabled=False,
        ).validate_voice_diagnostic()

    with pytest.raises(RuntimeError, match="TTS_RACE_ENABLED"):
        Settings(
            voice_diagnostic_mode=True,
            openrouter_api_key="test-only",
            whisper_interim_enabled=False,
        ).validate_voice_diagnostic()

    with pytest.raises(RuntimeError, match="MODEL_NAME"):
        Settings(
            voice_diagnostic_mode=True,
            openrouter_api_key="test-only",
            model_name="different/model",
            whisper_interim_enabled=False,
            tts_race_enabled=False,
        ).validate_voice_diagnostic()

    with pytest.raises(RuntimeError, match="TTS_PROVIDER"):
        Settings(
            voice_diagnostic_mode=True,
            openrouter_api_key="test-only",
            tts_provider="edge",
            whisper_interim_enabled=False,
            tts_race_enabled=False,
        ).validate_voice_diagnostic()

    Settings(
        voice_diagnostic_mode=True,
        openrouter_api_key="test-only",
        whisper_interim_enabled=False,
        tts_race_enabled=False,
    ).validate_voice_diagnostic()


def test_openrouter_chat_budget_blocks_before_second_client_call() -> None:
    class FakeStream:
        def __aiter__(self) -> AsyncIterator[object]:
            async def chunks() -> AsyncIterator[object]:
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Hi."))],
                    model="openai/gpt-4o-mini",
                    provider="test-provider",
                )

            return chunks()

    class FakeCompletions:
        calls = 0

        async def create(self, **_kwargs: object) -> FakeStream:
            self.calls += 1
            return FakeStream()

    async def run() -> None:
        settings = Settings(
            openrouter_api_key="test-only",
            voice_diagnostic_mode=True,
            whisper_interim_enabled=False,
            tts_race_enabled=False,
        )
        service = AIService(settings)
        completions = FakeCompletions()
        service._client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )  # type: ignore[assignment]
        async with provider_budget_scope(True) as budget:
            first = [token async for token in service.stream_reply([{"role": "user", "content": "hi"}])]
            assert first == ["Hi."]
            with pytest.raises(ProviderBudgetError):
                _ = [token async for token in service.stream_reply([{"role": "user", "content": "again"}])]
            assert completions.calls == 1
            assert budget is not None
            assert (await budget.snapshot())["openrouter_chat"]["attempted"] == 1

    asyncio.run(run())


def test_diagnostic_openai_client_disables_sdk_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(ai_service_module, "AsyncOpenAI", FakeOpenAI)
    diagnostic = AIService(
        Settings(
            openrouter_api_key="test-only",
            voice_diagnostic_mode=True,
            whisper_interim_enabled=False,
            tts_race_enabled=False,
        )
    )
    normal = AIService(Settings(openrouter_api_key="test-only", voice_diagnostic_mode=False))
    diagnostic._client_or_raise()
    normal._client_or_raise()
    assert captured[0]["max_retries"] == 0
    assert "max_retries" not in captured[1]


def test_openrouter_stt_budget_allows_only_one_http_request(tmp_path: Path) -> None:
    async def run() -> None:
        settings = Settings(
            openrouter_api_key="test-only",
            voice_diagnostic_mode=True,
            whisper_interim_enabled=False,
            tts_race_enabled=False,
            storage_dir=tmp_path,
        )
        fallback = WhisperService(settings)
        service = OpenRouterSTTService(settings, fallback)
        requests: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            return httpx.Response(200, json={"text": "hello Bella"})

        await service._client.aclose()
        service._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            transport=httpx.MockTransport(handler),
        )
        audio = tmp_path / "short.webm"
        audio.write_bytes(b"fake-audio")
        async with provider_budget_scope(True) as budget:
            assert await service.transcribe(audio) == "hello Bella"
            with pytest.raises(ProviderBudgetError):
                await service.transcribe(audio)
            assert requests == ["/api/v1/audio/transcriptions"]
            assert budget is not None
            assert (await budget.snapshot())["openrouter_stt"]["attempted"] == 1
        await service.close()

    asyncio.run(run())


def test_diagnostic_kokoro_skips_edge_and_rejects_second_request(tmp_path: Path) -> None:
    class CountingEdge:
        def __init__(self) -> None:
            self.calls = 0

        async def synthesize(self, _text: str, **_kwargs: object) -> str:
            self.calls += 1
            raise AssertionError("Edge is disabled in diagnostic mode")

        async def stream_audio(self, _text: str, **_kwargs: object) -> AsyncIterator[TTSAudioChunk]:
            self.calls += 1
            raise AssertionError("Edge is disabled in diagnostic mode")
            yield  # pragma: no cover

    async def run() -> None:
        settings = Settings(
            openrouter_api_key="test-only",
            voice_diagnostic_mode=True,
            whisper_interim_enabled=False,
            tts_race_enabled=False,
            storage_dir=tmp_path,
        )
        edge = CountingEdge()
        service = OpenRouterTTSService(settings, edge)  # type: ignore[arg-type]
        requests: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            return httpx.Response(200, content=_valid_mp3())

        await service._client.aclose()
        service._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            transport=httpx.MockTransport(handler),
        )
        async with provider_budget_scope(True) as budget:
            first = [chunk async for chunk in service.stream_audio("Hello there.")]
            assert first and all(chunk.provider == "kokoro" for chunk in first)
            with pytest.raises(RuntimeError, match="Edge fallback is disabled"):
                _ = [chunk async for chunk in service.stream_audio("Second phrase.")]
            assert requests == ["/api/v1/audio/speech"]
            assert edge.calls == 0
            assert budget is not None
            snapshot = await budget.snapshot()
            assert snapshot["kokoro_tts"]["attempted"] == 1
            assert snapshot["kokoro_tts"]["denied"] == 1
            assert snapshot["edge_tts"]["attempted"] == 0
        await service.close()

    asyncio.run(run())


def test_diagnostic_edge_fails_before_connecting() -> None:
    class NeverConnect:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def stream(self) -> AsyncIterator[dict[str, object]]:
            raise AssertionError("Edge must not start a remote stream")
            yield {}  # pragma: no cover

    async def run() -> None:
        settings = Settings(
            voice_diagnostic_mode=True,
            whisper_interim_enabled=False,
            tts_race_enabled=False,
        )
        service = EdgeTTSService(settings)
        from app.services import edge_tts_service as edge_module

        original = edge_module.edge_tts.Communicate
        edge_module.edge_tts.Communicate = NeverConnect  # type: ignore[assignment]
        try:
            async with provider_budget_scope(True):
                with pytest.raises(ProviderBudgetError):
                    _ = [chunk async for chunk in service.stream_audio("do not call Edge")]
        finally:
            edge_module.edge_tts.Communicate = original

    asyncio.run(run())


def test_bounded_full_voice_budget_allows_three_kokoro_calls_and_denies_fourth(
    tmp_path: Path,
) -> None:
    class CountingEdge:
        calls = 0

        async def synthesize(self, *_args: object, **_kwargs: object) -> str:
            self.calls += 1
            raise AssertionError("Edge is disabled during the bounded voice test")

    async def run() -> None:
        settings = Settings(
            openrouter_api_key="test-only",
            bounded_full_voice_test=True,
            whisper_interim_enabled=False,
            tts_race_enabled=False,
            storage_dir=tmp_path,
        )
        edge = CountingEdge()
        service = OpenRouterTTSService(settings, edge)  # type: ignore[arg-type]
        requests: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            return httpx.Response(200, content=_valid_mp3())

        await service._client.aclose()
        service._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            transport=httpx.MockTransport(handler),
        )
        async with provider_budget_scope("bounded_full_voice_test") as budget:
            for phrase in ("First phrase.", "Second phrase.", "Third phrase."):
                audio = [chunk async for chunk in service.stream_audio(phrase)]
                assert audio and all(chunk.provider == "kokoro" for chunk in audio)
            with pytest.raises(RuntimeError, match="Edge fallback is disabled"):
                _ = [chunk async for chunk in service.stream_audio("Fourth phrase.")]
            with pytest.raises(ValueError, match="local safety limit"):
                _ = [
                    chunk
                    async for chunk in service.stream_audio(
                        "x" * (BOUNDED_FULL_TTS_MAX_INPUT_CHARS + 1)
                    )
                ]
            assert requests == ["/api/v1/audio/speech"] * 3
            assert edge.calls == 0
            assert budget is not None
            snapshot = await budget.snapshot()
            assert snapshot["kokoro_tts"] == {"attempted": 3, "denied": 1, "limit": 3}
            assert snapshot["edge_tts"] == {"attempted": 0, "denied": 0, "limit": 0}
        await service.close()

    asyncio.run(run())


def test_diagnostic_kokoro_rejects_alternate_voice_before_provider_call(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        settings = Settings(
            openrouter_api_key="test-only",
            voice_diagnostic_mode=True,
            whisper_interim_enabled=False,
            tts_race_enabled=False,
            storage_dir=tmp_path,
        )
        service = OpenRouterTTSService(settings, EdgeTTSService(settings))
        async with provider_budget_scope(True):
            with pytest.raises(RuntimeError, match="Edge fallback is disabled"):
                _ = [
                    chunk
                    async for chunk in service.stream_audio("Hello.", voice="af_heart")
                ]
        await service.close()

    asyncio.run(run())
