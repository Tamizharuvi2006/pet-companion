"""Offline, real-browser MP3 streaming acceptance using generated tone files.

Run with ``uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt``
and ``.venv/Scripts/python.exe -m pytest tests/browser -q``. The test uses the
installed Microsoft Edge channel and substitutes local fake AI/STT/TTS services;
it never contacts OpenRouter or Edge TTS.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.core.config import get_settings
from app.main import app
from app.services.mp3_stream import has_complete_mp3_frames
from app.services.tts_service import TTSAudioChunk


class _FixtureAI:
    def __init__(self) -> None:
        self.turns = 0

    async def stream_reply(self, _messages: list[dict[str, str]]) -> AsyncIterator[str]:
        self.turns += 1
        yield "You did great; "
        await asyncio.sleep(0.55)
        yield (
            " Here is a clean second phrase to test the browser audio stream and make "
            "sure the sequence remains clear. This final sentence confirms that Bella "
            "can keep speaking while the text finishes."
        )

    async def close(self) -> None:
        return None


class _FixtureTTS:
    def __init__(self, audio_tracks: list[bytes], *, chunk_delay: float = 0.12) -> None:
        self._audio_tracks = audio_tracks
        self._calls = 0
        self._chunk_delay = chunk_delay

    async def stream_audio(self, _text: str, **_options: object) -> AsyncIterator[TTSAudioChunk]:
        audio = self._audio_tracks[self._calls % len(self._audio_tracks)]
        self._calls += 1
        for offset in range(0, len(audio), 1024):
            yield TTSAudioChunk(provider="generated-fixture", data=audio[offset : offset + 1024])
            await asyncio.sleep(self._chunk_delay)

    async def close(self) -> None:
        return None


def _generated_mp3(path: Path, frequency: int) -> bytes:
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration=1.25",
            "-ac", "1", "-ar", "44100", "-b:a", "64k",
            "-id3v2_version", "0", "-write_xing", "0", str(path),
        ],
        check=True,
        capture_output=True,
    )
    data = path.read_bytes()
    assert has_complete_mp3_frames(data), "FFmpeg fixture must contain valid MP3 frames"
    return data


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required for generated audio")
@pytest.mark.parametrize("scenario", ["success", "browser_error", "new_turn_during_playback"])
def test_real_edge_media_source_plays_ordered_generated_mp3_while_llm_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("TTS_FIRST_CHUNK_WORDS", "6")
    monkeypatch.setenv("VOICE_DIAGNOSTIC_MODE", "false")
    monkeypatch.setenv("BOUNDED_FULL_VOICE_TEST", "false")
    # This acceptance fixture verifies the legacy GPT text + MP3 TTS pipeline;
    # keep it explicit now that Audio Mini is the application default.
    monkeypatch.setenv("VOICE_ENGINE_DEFAULT", "current")
    get_settings.cache_clear()
    tracks = [
        _generated_mp3(tmp_path / f"tone-{frequency}.mp3", frequency)
        for frequency in (523, 659, 784)
    ]

    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False)
    )
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    original_ai: Any = None
    original_tts: Any = None
    original_transcribe: Any = None
    try:
        deadline = time.monotonic() + 20
        while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "offline FastAPI server did not become ready"
        port = server.servers[0].sockets[0].getsockname()[1]
        original_ai, original_tts = app.state.ai, app.state.tts
        original_transcribe = app.state.whisper.transcribe
        app.state.ai = _FixtureAI()
        app.state.tts = _FixtureTTS(
            tracks,
            chunk_delay=0.001 if scenario == "new_turn_during_playback" else 0.12,
        )

        async def fake_transcribe(_path: Path, *, interim: bool = False) -> str:
            return "hello bella"

        app.state.whisper.transcribe = fake_transcribe
        base_url = f"http://127.0.0.1:{port}"

        with sync_playwright() as driver:
            try:
                browser = driver.chromium.launch(
                    channel="msedge",
                    headless=True,
                    args=[
                        "--use-fake-device-for-media-stream",
                        "--use-fake-ui-for-media-stream",
                        "--autoplay-policy=no-user-gesture-required",
                    ],
                )
            except PlaywrightError as error:
                pytest.skip(f"Installed Microsoft Edge could not launch headlessly: {error}")
            try:
                context = browser.new_context()
                context.grant_permissions(["microphone"], origin=base_url)
                page = context.new_page()
                page_errors: list[str] = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.add_init_script(
                    """(() => {
                      window.__bellaVoiceEvents = [];
                      window.__bellaExpressions = [];
                      window.addEventListener('bella-expression',event=>window.__bellaExpressions.push(event.detail));
                      const original = console.info.bind(console);
                      console.info = (...args) => {
                        if (args[0] === '[bella_voice_timing]' && typeof args[1] === 'string') {
                          try { window.__bellaVoiceEvents.push(JSON.parse(args[1])); } catch {}
                        }
                        original(...args);
                      };
                    })();"""
                )
                page.goto(base_url, wait_until="domcontentloaded")
                page.locator("#voice-engine").select_option("current")
                face_page=context.new_page()
                face_page.goto(base_url+'/face.html',wait_until='domcontentloaded')
                face_page.select_option('#face-mode','browser')
                page.locator("#status").get_by_text("Ready", exact=True).wait_for(timeout=10_000)
                supported = page.evaluate("MediaSource.isTypeSupported('audio/mpeg')")
                if not supported:
                    pytest.skip("This Edge build does not support MediaSource audio/mpeg")

                talk_button = page.locator("#push-to-talk")
                talk_button.dispatch_event(
                    "pointerdown", {"pointerType": "mouse", "button": 0, "buttons": 1}
                )
                page.locator("#status").get_by_text("Listening…", exact=True).wait_for(timeout=10_000)
                page.wait_for_timeout(650)
                talk_button.dispatch_event(
                    "pointerup", {"pointerType": "mouse", "button": 0, "buttons": 0}
                )
                if scenario == "browser_error":
                    page.wait_for_function(
                        "window.__bellaVoiceEvents?.some((event) => event.stage === 'first_playback_started')",
                        timeout=20_000,
                    )
                    page.evaluate(
                        "document.querySelector('#player').dispatchEvent(new Event('error'))"
                    )
                    page.get_by_text(
                        "Bella's audio was interrupted in the browser. You can retry the reply audio.",
                        exact=True,
                    ).wait_for(timeout=5_000)
                    page.wait_for_function(
                        "window.__bellaVoiceEvents?.some((event) => event.stage === 'reply_complete_received')",
                        timeout=20_000,
                    )
                elif scenario == "new_turn_during_playback":
                    page.wait_for_function(
                        "window.__bellaVoiceEvents?.some((event) => event.stage === 'first_playback_started')",
                        timeout=20_000,
                    )
                    talk_button.dispatch_event(
                        "pointerdown", {"pointerType": "mouse", "button": 0, "buttons": 1}
                    )
                    page.locator("#status").get_by_text("Listening…", exact=True).wait_for(timeout=10_000)
                    page.wait_for_timeout(250)
                    talk_button.dispatch_event(
                        "pointerup", {"pointerType": "mouse", "button": 0, "buttons": 0}
                    )
                    page.wait_for_function(
                        "window.__bellaVoiceEvents?.filter((event) => event.stage === 'first_playback_started').length >= 2",
                        timeout=20_000,
                    )
                    page.wait_for_function(
                        "window.__bellaVoiceEvents?.filter((event) => event.stage === 'reply_complete_received').length >= 2",
                        timeout=20_000,
                    )
                    page.wait_for_function(
                        "window.__bellaVoiceEvents?.some((event) => event.stage === 'playback_completed' && event.trace_id !== window.__bellaVoiceEvents.find((candidate) => candidate.stage === 'first_playback_started')?.trace_id)",
                        timeout=20_000,
                    )
                else:
                    page.wait_for_function(
                        "window.__bellaVoiceEvents?.some((event) => event.stage === 'playback_completed')",
                        timeout=20_000,
                    )

                events = page.evaluate("window.__bellaVoiceEvents")
                expressions=page.evaluate('window.__bellaExpressions')
                names=[event['expression'] for event in expressions]
                assert names.index('listening') < names.index('thinking') < names.index('speaking')
                assert all(event['destination']=='browser' for event in expressions)
                assert all('text' not in event and 'token' not in event for event in expressions)
                if scenario=='success':
                    face_page.wait_for_function("document.querySelector('#state').textContent==='IDLE'")
                    assert page.evaluate('BellaExpressions.controller.current()')=='idle'
                elif scenario=='browser_error':
                    assert 'error' in names
                stages = [event["stage"] for event in events]
                playback_started = stages.index("first_playback_started")
                reply_finished = stages.index("reply_complete_received")
                if scenario == "new_turn_during_playback":
                    playback_events = [event for event in events if event["stage"] == "first_playback_started"]
                    assert len({event["trace_id"] for event in playback_events}) == 2
                    first_trace_id, second_trace_id = (event["trace_id"] for event in playback_events)
                    assert not any(
                        event["stage"] == "playback_completed" and event["trace_id"] == first_trace_id
                        for event in events
                    ), "the new turn should interrupt, not mix with, the old playback"
                    assert any(
                        event["stage"] == "playback_completed" and event["trace_id"] == second_trace_id
                        for event in events
                    )
                elif scenario != "browser_error":
                    assert playback_started < reply_finished, "audio should start while the LLM is still generating"
                assert stages.index("first_audio_bytes_received") < playback_started
                if scenario == "success":
                    assert playback_started < stages.index("audio_chunk_stream_end_received"), (
                        "browser playback should begin before the first phrase stream finishes"
                    )
                expected_stream_count = 6 if scenario == "new_turn_during_playback" else 3
                assert stages.count("audio_stream_start_received") == expected_stream_count
                assert stages.count("audio_chunk_stream_end_received") == expected_stream_count
                if scenario == "browser_error":
                    assert "playback_error" in stages
                    assert "playback_completed" not in stages
                    assert page.locator("#retry-audio").is_visible()
                elif scenario == "success":
                    assert stages.index("playback_completed") > reply_finished
                    assert "playback_waiting_for_audio" not in stages
                assert not page_errors, f"browser JavaScript errors: {page_errors}"
                if scenario == "success" and (capture := os.getenv("BELLA_OFFLINE_SCREENSHOT")):
                    page.set_viewport_size({"width": 860, "height": 560})
                    page.screenshot(path=capture, animations="disabled")
                    page.set_viewport_size({"width": 390, "height": 760})
                    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
                    assert page.locator("#text-input").is_visible()
                    mobile = Path(capture)
                    page.screenshot(path=mobile.with_stem(mobile.stem + "-mobile"), animations="disabled")
                if scenario == "success":
                    assert not {
                        "media_source_error", "media_append_error", "media_pending_limit",
                        "media_end_error", "playback_error", "audio_chunk_stream_aborted",
                    }.intersection(stages)
                offsets = {
                    stage: next(event["offset_ms"] for event in events if event["stage"] == stage)
                    for stage in (
                        "first_text_delta_received",
                        "first_audio_bytes_received",
                        "first_playback_started",
                        "audio_chunk_stream_end_received",
                        "reply_complete_received",
                    )
                }
                if scenario == "success":
                    stages_by_name = {event["stage"]: event for event in events}
                    assert 0 <= stages_by_name["final_transcript_received"]["since_recording_stop_ms"] <= stages_by_name["first_playback_started"]["since_recording_stop_ms"]
                    offsets["playback_completed"] = next(
                        event["offset_ms"]
                        for event in events
                        if event["stage"] == "playback_completed"
                    )
                metrics = {
                    "clock": "browser performance.now() monotonic offsets",
                    "first_text_to_first_audio_bytes_ms": offsets["first_audio_bytes_received"] - offsets["first_text_delta_received"],
                    "first_text_to_playback_ms": offsets["first_playback_started"] - offsets["first_text_delta_received"],
                    "playback_before_reply_complete_ms": offsets["reply_complete_received"] - offsets["first_playback_started"],
                    "playback_before_first_tts_stream_end_ms": offsets["audio_chunk_stream_end_received"] - offsets["first_playback_started"],
                    "playback_complete_from_first_text_ms": (
                        offsets["playback_completed"] - offsets["first_text_delta_received"]
                        if scenario == "success" else None
                    ),
                    "scenario": scenario,
                    "ordered_audio_streams": stages.count("audio_stream_start_received"),
                    "audio_stream_ends": stages.count("audio_chunk_stream_end_received"),
                }
                print("browser_acceptance_metrics=" + json.dumps(metrics, sort_keys=True))
                if scenario == "success":
                    page.reload(wait_until="domcontentloaded")
                    page.locator("#status").get_by_text("Ready", exact=True).wait_for()
                    page.set_viewport_size({"width": 1920, "height": 980})
                    page.locator("#history-drawer").wait_for(state="visible")
                    assert page.locator("[data-pet-sound]").count() == 1
                    assert page.locator("#text-input").evaluate(
                        "(el) => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }"
                    )
                    saved = page.locator("#history-list").get_by_role("button", name="hello bella", exact=True)
                    saved.click()
                    page.locator(".message.assistant").get_by_role("button", name="Copy", exact=True).wait_for()
                    page.locator(".message.assistant").get_by_role("button", name="Read aloud", exact=True).wait_for()
                    page.locator("#new-chat").click()
                    assert page.locator(".message").count() == 0
                    if capture := os.getenv("BELLA_OFFLINE_SCREENSHOT"):
                        page.set_viewport_size({"width": 1120, "height": 680})
                        page.locator("#status").get_by_text("Ready", exact=True).wait_for()
                        target = Path(capture)
                        page.screenshot(path=target.with_stem(target.stem + "-welcome"), animations="disabled")
                    composer = page.locator("#text-input")
                    composer.fill("First line")
                    composer.press("End")
                    composer.press("Shift+Enter")
                    composer.press("S")
                    assert composer.input_value() == "First line\nS"
                    page.locator("#history-list summary").click()
                    page.once("dialog", lambda dialog: dialog.accept("Playback check"))
                    page.get_by_role("button", name="Rename", exact=True).click()
                    page.locator("#history-list").get_by_role("button", name="Playback check").wait_for()
                    page.locator("#history-list summary").click()
                    page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_role("button", name="Delete", exact=True).click()
                    assert page.locator("#history-list").inner_text() == "No saved chats yet."
            finally:
                browser.close()
    finally:
        if original_ai is not None:
            app.state.ai = original_ai
        if original_tts is not None:
            app.state.tts = original_tts
        if original_transcribe is not None:
            app.state.whisper.transcribe = original_transcribe
        server.should_exit = True
        server_thread.join(timeout=10)
        get_settings.cache_clear()
