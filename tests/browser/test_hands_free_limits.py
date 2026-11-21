"""Real MediaRecorder, fake transport: no provider calls."""
import functools
import http.server
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


def test_long_capture_is_bounded_and_session_listens_again():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(Path('app/frontend').resolve()))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True, args=[
                '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'])
            try:
                page = browser.new_page(permissions=['microphone'])
                page.route('**/auth/session', lambda route: route.fulfill(
                    json={'required': False, 'authenticated': True}))
                page.route('**/tts/config', lambda route: route.fulfill(json={}))
                page.add_init_script("""(() => {
                  window.sent = [];
                  class FakeSocket extends EventTarget {
                    static OPEN=1; readyState=1;
                    constructor() { super(); setTimeout(()=>this.onopen?.(),100); }
                    send(raw) {
                      const event=JSON.parse(raw); window.sent.push(event);
                      if(event.type==='client_capabilities') setTimeout(()=>this.onmessage?.({data:JSON.stringify({type:'recording_limits',max_seconds:3})}),0);
                    }
                    close() { this.readyState=3; this.dispatchEvent(new Event('close')); }
                  }
                  window.WebSocket=FakeSocket;
                  AnalyserNode.prototype.getByteTimeDomainData=function(data){data.fill(150)};
                })();""")
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                page.locator('#status').get_by_text('Ready', exact=True).wait_for()
                page.locator('#voice-mode').click()
                page.wait_for_function("window.sent.some(x=>x.type==='stop_recording')", timeout=5000)
                assert page.evaluate("sent.filter(x=>x.type==='audio_chunk').length") > 0
                assert page.locator('#voice-session').is_visible()
                assert 'Maximum recording duration exceeded' not in page.locator('body').inner_text()
                # Playback completion is covered by generated-MP3 tests; here
                # isolate the session's resume transition after the bounded turn.
                page.evaluate('resumeHandsFree()')
                page.wait_for_function('isRecording')
                page.locator('#end-voice-mode').click()
                page.wait_for_function('!isRecording && !isFinalizingAudio')
                assert page.evaluate('stream.getTracks().every(track=>track.readyState === "ended")')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
