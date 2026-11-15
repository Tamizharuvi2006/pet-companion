"""Browser checks that pet TTS cannot consume the bounded voice-test latch."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.core.config import Settings
from app.main import app
from app.services.diagnostic_session import DiagnosticSessionLatch
from app.services.whisper_service import WhisperService


@pytest.mark.parametrize("bounded_test_mode", [True, False])
def test_page_load_never_preloads_pet_tts_and_click_is_mode_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bounded_test_mode: bool
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    settings = Settings(
        environment="development",
        openrouter_api_key="offline-browser-fixture-only",
        bounded_full_voice_test=bounded_test_mode,
        whisper_interim_enabled=not bounded_test_mode,
        tts_race_enabled=not bounded_test_mode,
        storage_dir=tmp_path,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    async def no_model_load(_self: WhisperService) -> None:
        return None

    claims: list[str] = []
    original_claim = DiagnosticSessionLatch.claim

    async def observe_claim(self: DiagnosticSessionLatch, source: str) -> None:
        claims.append(source)
        await original_claim(self, source)

    monkeypatch.setattr(WhisperService, "load", no_model_load)
    monkeypatch.setattr(DiagnosticSessionLatch, "claim", observe_claim)

    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False)
    )
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "offline Bella server did not become ready"
        port = server.servers[0].sockets[0].getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"

        with sync_playwright() as driver:
            try:
                browser = driver.chromium.launch(
                    channel="msedge",
                    headless=True,
                    args=["--autoplay-policy=no-user-gesture-required"],
                )
            except PlaywrightError as error:
                pytest.skip(f"Installed Microsoft Edge could not launch headlessly: {error}")
            try:
                page = browser.new_page()
                page.set_viewport_size({"width": 390, "height": 844})
                tts_posts: list[str] = []
                paid_posts: list[str] = []
                page.on(
                    "request",
                    lambda request: paid_posts.append(request.url)
                    if request.method == "POST"
                    and any(path in request.url for path in ("/tts", "/chat", "/stt", "/talk"))
                    else None,
                )
                page.add_init_script(
                    """(() => {
                      const originalPlay = HTMLMediaElement.prototype.play;
                      HTMLMediaElement.prototype.play = function() {
                        const source = this.currentSrc || this.src || '';
                        if (source.includes('bella-meow.ogg')) {
                          setTimeout(() => this.dispatchEvent(new Event('ended')), 0);
                          return Promise.resolve();
                        }
                        if (source.includes('/audio/pet-fixture.mp3')) return Promise.resolve();
                        return originalPlay.call(this);
                      };
                    })();"""
                )

                def intercept_tts(route) -> None:
                    tts_posts.append(route.request.url)
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"audio_url": "/audio/pet-fixture.mp3"}),
                    )

                page.route("**/tts", intercept_tts)
                page.goto(base_url, wait_until="domcontentloaded")
                page.locator("#status").get_by_text("Ready", exact=True).wait_for(timeout=10_000)
                config = page.evaluate(
                    "fetch('/client-config', {credentials:'same-origin'}).then((r) => r.json())"
                )
                assert config["pet_voice_synthesis_enabled"] is (not bounded_test_mode)

                # Longer than the legacy 1.2-second preload delay.
                page.wait_for_timeout(1_500)
                assert tts_posts == []
                assert paid_posts == []
                assert claims == []

                page.locator("[data-pet-sound]").first.click()
                page.locator("#pet-speech").wait_for(state="visible", timeout=5_000)
                if bounded_test_mode:
                    page.wait_for_timeout(250)
                    assert tts_posts == []
                    assert paid_posts == []
                    assert claims == []
                else:
                    page.wait_for_timeout(250)
                    assert len(tts_posts) == 1
                    assert len(paid_posts) == 1
                    assert claims == []  # The test latch is disabled in normal mode.
            finally:
                browser.close()
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
