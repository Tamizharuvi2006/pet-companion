"""Real-browser face-only integration using an offline local ASGI server."""
import threading
import time

import pytest
import uvicorn
from app.core.config import get_settings
from app.main import app

pytest.importorskip('playwright.sync_api')
from playwright.sync_api import sync_playwright


def test_face_simulation_and_mock_connected_dashboard(monkeypatch):
    monkeypatch.setenv('BELLA_DEVICE_TOKENS','bella=offline-test-token-12345')
    get_settings.cache_clear()
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        deadline=time.monotonic()+20
        while not server.started and time.monotonic()<deadline:time.sleep(.02)
        assert server.started
        port=server.servers[0].sockets[0].getsockname()[1]
        with sync_playwright() as driver:
            browser=driver.chromium.launch(channel='msedge',headless=True)
            try:
                page=browser.new_page();errors=[];posts=[];api_reads=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:posts.append(request.url) if request.method=='POST' else None)
                page.on('request',lambda request:api_reads.append(request.url) if '/api/' in request.url else None)
                page.goto(f'http://127.0.0.1:{port}/face.html')
                page.wait_for_timeout(200)
                assert api_reads==[]
                before=page.locator('canvas').evaluate('(c)=>c.toDataURL()')
                for state in ['CURIOUS','HAPPY','LOVE','ERROR','THINKING','IDLE']:
                    page.locator(f'button[data-state="{state}"]').first.click()
                    page.wait_for_timeout(150)
                    assert page.locator('#state').inner_text()==state
                page.locator('#pads button').nth(2).click()
                page.wait_for_timeout(100)
                assert page.locator('#state').inner_text()=='CURIOUS'
                assert page.locator('canvas').evaluate('(c)=>c.toDataURL()')!=before
                assert posts==[] and api_reads==[]
                page.route('**/api/face/devices',lambda route:route.fulfill(json=[{
                    'device_id':'bella','connected':True,'face_expression':'happy',
                    'state':'IDLE','last_heartbeat':'fixture','last_touch':2,
                    'command_status':'accepted_by_engine'}]))
                page.route('**/api/face/bella/expression',lambda route:route.fulfill(status=202,json={'status':'pending'}))
                page.select_option('#face-mode','connected')
                page.wait_for_function("document.querySelector('#state').textContent==='HAPPY'")
                assert 'Online' in page.locator('#face-device-state').inner_text()
                page.locator('#emotions button[data-state="LOVE"]').click()
                page.wait_for_timeout(100)
                assert len(posts)==1 and '/api/face/bella/expression' in posts[0]
                assert 'pending' in page.locator('#face-connection').inner_text()
                page.select_option('#face-mode','simulation')
                assert errors==[]
            finally:browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10)
