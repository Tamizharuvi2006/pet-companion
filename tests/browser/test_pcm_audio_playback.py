"""Browser-side PCM scheduling test with a local fake WebSocket, no provider calls."""

from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


def test_browser_plays_streamed_pcm_from_the_audio_mini_mode() -> None:
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(Path("app/frontend").resolve()),
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
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
                page_errors: list[str] = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.add_init_script(
                    r"""(() => {
                      window.__bellaVoiceEvents = [];
                      const original = console.info.bind(console);
                      console.info = (...args) => {
                        if (args[0] === '[bella_voice_timing]' && typeof args[1] === 'string') {
                          try { window.__bellaVoiceEvents.push(JSON.parse(args[1])); } catch {}
                        }
                        original(...args);
                      };
                      class FakeSocket extends EventTarget {
                        static OPEN = 1;
                        constructor() { super(); this.readyState = 0; this.binaryType = 'blob';
                          setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0); }
                        send(raw) {
                          const event = JSON.parse(raw);
                          if (event.type === 'client_capabilities') {
                            setTimeout(() => {
                              this.onmessage?.({data: JSON.stringify({type:'recording_limits', max_seconds:30})});
                              this.onmessage?.({data: JSON.stringify({type:'voice_engine_selected', voice_engine:event.voice_engine || 'current'})});
                            }, 0);
                          }
                          if (event.type === 'text') this.playSyntheticPcm();
                        }
                        playSyntheticPcm() {
                          const trace = 'offline-pcm-test';
                          this.onmessage?.({data: JSON.stringify({type:'pcm_stream_start', trace_id:trace, codec:'pcm_s16le', sample_rate:24000, channels:1})});
                          this.onmessage?.({data: JSON.stringify({type:'reply_delta', trace_id:trace, session_id:'offline-session', text:'A streamed PCM reply.'})});
                          const sampleRate = 24000, sampleCount = 14400;
                          const pcm = new ArrayBuffer(sampleCount * 2), view = new DataView(pcm);
                          for (let i=0; i<sampleCount; i++) view.setInt16(i*2, Math.round(Math.sin(2*Math.PI*440*i/sampleRate)*7000), true);
                          let offset = 0;
                          const timer = setInterval(() => {
                            const end = Math.min(pcm.byteLength, offset + 2400);
                            this.onmessage?.({data: pcm.slice(offset, end)});
                            offset = end;
                            if (offset >= pcm.byteLength) {
                              clearInterval(timer);
                              this.onmessage?.({data: JSON.stringify({type:'reply', trace_id:trace, session_id:'offline-session', text:'A streamed PCM reply.'})});
                              this.onmessage?.({data: JSON.stringify({type:'pcm_stream_end', trace_id:trace})});
                            }
                          }, 12);
                        }
                        close() { this.readyState = 3; this.dispatchEvent(new Event('close')); }
                      }
                      window.WebSocket = FakeSocket;
                    })();"""
                )
                page.route("**/auth/session", lambda route: route.fulfill(json={"required": False, "authenticated": True}))
                page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="domcontentloaded")
                page.locator("#status").get_by_text("Ready", exact=True).wait_for(timeout=10_000)
                page.locator("#voice-engine").select_option("gpt_audio_mini")
                page.locator("#text-input").fill("Say hello.")
                page.locator("#text-input").press("Enter")
                page.get_by_text("A streamed PCM reply.", exact=True).wait_for(timeout=5_000)
                page.wait_for_function(
                    "window.__bellaVoiceEvents?.some(event => event.stage === 'playback_completed')",
                    timeout=8_000,
                )
                stages = [event["stage"] for event in page.evaluate("window.__bellaVoiceEvents")]
                assert stages.index("first_audio_bytes_received") < stages.index("first_playback_started")
                assert stages.index("first_playback_started") < stages.index("playback_completed")
                assert not page_errors, page_errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
