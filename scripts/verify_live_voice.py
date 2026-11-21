"""Explicit opt-in, single-turn browser acceptance using existing OpenRouter models.

Run as a module: python -m scripts.verify_live_voice --authorize-paid
Requires a synthetic WAV and installed Edge. No secrets or .env are modified.
"""

import argparse
import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-paid", action="store_true")
    parser.add_argument("--hands-free", action="store_true")
    parser.add_argument("--turns", type=int, choices=(1, 2, 3), default=1,
                        help="Repeat on one backend; provider caps apply per turn")
    parser.add_argument("--wav", type=Path, default=Path("tmp/pdfs/bella-table-retest.wav"))
    parser.add_argument("--output", type=Path, default=Path("tmp/voice-live-results.json"))
    args = parser.parse_args()
    if not args.authorize_paid:
        parser.error("Requires --authorize-paid; caps: 1 STT, 1 chat, 3 Kokoro, 0 Edge")
    if not args.wav.is_file():
        parser.error("Synthetic WAV not found")
    for name in ("WHISPER_PRELOAD_ENABLED", "WHISPER_INTERIM_ENABLED", "VOICE_DIAGNOSTIC_MODE", "BOUNDED_FULL_VOICE_TEST"):
        os.environ[name] = "false"
    import uvicorn
    from playwright.sync_api import sync_playwright
    from app.main import app
    import app.api.websocket as websocket_api
    from app.services.provider_budget import provider_budget_scope

    counts = []

    @asynccontextmanager
    async def capped_scope(_mode):
        async with provider_budget_scope("bounded_full_voice_test") as budget:
            try:
                yield budget
            finally:
                counts.append(await budget.snapshot())

    websocket_api.provider_budget_scope = capped_scope
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    events, errors, media_events = [], [], []
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not server.started:
            raise RuntimeError("Isolated acceptance server did not start")
        app.state.ai._client = app.state.ai._client_or_raise().with_options(max_retries=0)
        url = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
        def run_browser_turn(driver):
            browser = driver.chromium.launch(channel="msedge", headless=True, args=[
                "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                f"--use-file-for-fake-audio-capture={args.wav.resolve()}%noloop",
                "--autoplay-policy=no-user-gesture-required",
            ])
            try:
                page = browser.new_page(permissions=["microphone"])

                def console(message):
                    if message.text.startswith("[bella_voice_timing] "):
                        events.append(json.loads(message.text.split(" ", 1)[1]))

                first_event = len(events)
                page.on("console", console)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url)
                page.evaluate("""() => {
                    window.__bellaMediaEvents = [];
                    const player = document.querySelector('#player');
                    for (const type of ['playing', 'waiting', 'stalled', 'ended', 'error']) {
                        player.addEventListener(type, () => window.__bellaMediaEvents.push({
                            type, at: performance.now(), currentTime: player.currentTime
                        }));
                    }
                }""")
                page.locator("#status").get_by_text("Ready", exact=True).wait_for(timeout=10000)
                mic = page.locator("#push-to-talk")
                if args.hands_free:
                    page.locator('#voice-mode').click()
                else:
                    mic.dispatch_event("pointerdown", {"pointerType": "mouse", "button": 0, "buttons": 1})
                    page.wait_for_timeout(3400)
                    mic.dispatch_event("pointerup", {"pointerType": "mouse", "button": 0, "buttons": 0})
                for _ in range(80):
                    page.wait_for_timeout(500)
                    if any(event["stage"] == "playback_completed" for event in events[first_event:]):
                        break
                media_events.append(page.evaluate('window.__bellaMediaEvents'))
                if args.hands_free:
                    page.wait_for_timeout(700)
                    print('Hands-free listening resumed:', page.evaluate('isRecording'), flush=True)
                    assert any(event['stage'] == 'playback_completed' for event in events[first_event:]), 'Voice reply did not complete'
                    assert page.evaluate('isRecording'), 'Hands-free listening did not resume'
                    page.locator('#end-voice-mode').click()
            finally:
                browser.close()
        with sync_playwright() as driver:
            for _ in range(args.turns):
                run_browser_turn(driver)
    finally:
        server.should_exit = True
        thread.join(8)
        result = {"synthetic_input": str(args.wav), "events": events, "page_errors": errors, "media_events": media_events, "provider_counts": counts}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
