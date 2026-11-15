import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings
from app.device.registry import DeviceRegistry
from app.device.face import FaceCommand, FaceReport

TOKEN='offline-device-token-123456789'


def hello(ws):
    ws.send_json({'type':'hello','version':1,'device_id':'bella','token':TOKEN,
                  'capabilities':{'face_protocol_v1':True}})
    assert ws.receive_json()['type']=='device_ready'


def test_face_command_report_ack_reconnect_and_latch(monkeypatch):
    monkeypatch.setenv('BELLA_DEVICE_TOKENS',f'bella={TOKEN}')
    get_settings.cache_clear()
    with TestClient(app) as client:
        latch=asyncio.run(app.state.diagnostic_session.snapshot())
        with client.websocket_connect('/ws/device') as ws:
            hello(ws)
            result=client.post('/api/face/bella/expression',json={'expression':'love'})
            assert result.status_code==202
            assert result.json()['physical_delivery_confirmed'] is False
            ws.send_json({'type':'ping','version':1,'state':'IDLE'})
            assert ws.receive_json()['type']=='pong'
            command=ws.receive_json()
            assert command['expression']=='love'
            ws.send_json({'type':'face_ack','version':1,'face_version':1,'command_id':command['command_id']})
            for seq,expression in [(1,'love'),(1,'angry')]:
                ws.send_json({'type':'face_report','version':1,'face_version':1,'sequence':seq,'expression':expression,'touch_pad':2})
            ws.send_json({'type':'ping','version':1})
            assert ws.receive_json()['type']=='pong'
            record=client.get('/api/face/devices').json()[0]
            assert record['face_expression']=='love'
            assert record['last_touch']==2
            assert record['command_status']=='accepted_by_engine'
            assert TOKEN not in json.dumps(record)
        assert client.get('/api/face/devices').json()[0]['connected'] is False
        assert client.post('/api/face/bella/expression',json={'expression':'happy'}).status_code==409
        with client.websocket_connect('/ws/device') as ws:
            hello(ws)
            ws.send_json({'type':'ping','version':1})
            assert ws.receive_json()['type']=='pong'
        assert asyncio.run(app.state.diagnostic_session.snapshot())==latch


def test_face_browser_auth_and_origin(monkeypatch):
    monkeypatch.setenv('ENVIRONMENT','production')
    monkeypatch.setenv('BELLA_ACCESS_PASSWORD','offline-password-long-enough')
    monkeypatch.setenv('BELLA_SESSION_SECRET','s'*48)
    monkeypatch.setenv('BELLA_ALLOWED_ORIGINS','https://bella.example')
    monkeypatch.setenv('BELLA_DEVICE_TOKENS',f'bella={TOKEN}')
    get_settings.cache_clear()
    with TestClient(app,base_url='https://bella.example') as client:
        assert client.get('/api/face/devices').status_code==401
        assert client.post('/api/face/bella/expression',json={'expression':'idle'},headers={'Origin':'https://evil.example'}).status_code==403
        assert client.post('/auth/login',json={'password':'offline-password-long-enough'},headers={'Origin':'https://bella.example'}).status_code==200
        assert client.get('/api/face/devices').status_code==200
        assert client.post('/api/face/unknown/expression',json={'expression':'idle'},headers={'Origin':'https://bella.example'}).status_code==404


def test_face_registry_latest_bounded_and_disconnect():
    async def run():
        registry=DeviceRegistry()
        await registry.connected('bella','test',{'face_protocol_v1':True},{})
        assert not await registry.connected('bella','test',{}, {})
        for _ in range(100):
            await registry.command('bella','happy',1800)
        assert len(registry._commands)==1
        last=await registry.command('bella','wink',1800)
        assert (await registry.take_command('bella'))['command_id']==last
        assert await registry.take_command('bella') is None
        await registry.command('bella','idle',1800)
        registry._commands['bella']['expires']=0
        assert await registry.take_command('bella') is None
        await registry.disconnected('bella')
        assert await registry.command('bella','idle',1800) is None
    asyncio.run(run())


@pytest.mark.parametrize('body',[{'expression':'gpio'},{'expression':'idle','duration_ms':9000},{'expression':'idle','pin':12}])
def test_invalid_face_commands(body):
    with pytest.raises(ValueError):FaceCommand.model_validate(body)


def test_report_rejects_invalid_touch():
    with pytest.raises(ValueError):FaceReport(expression='happy',sequence=1,touch_pad=5)


def test_cloud_can_skip_local_whisper_preload(monkeypatch):
    from app.core.config import Settings
    from app.services.openrouter_stt_service import OpenRouterSTTService
    class Fallback:
        async def load(self):raise AssertionError('Cloud preload must not load local model')
        async def close(self):pass
    async def run():
        service=OpenRouterSTTService(Settings(whisper_preload_enabled=False),Fallback())
        await service.load()
        await service.close()
    asyncio.run(run())


def test_face_liveness_timeout(monkeypatch):
    monkeypatch.setenv('BELLA_DEVICE_TOKENS',f'bella={TOKEN}')
    monkeypatch.setattr('app.device.websocket.DEVICE_IDLE_TIMEOUT_SECONDS',.05)
    get_settings.cache_clear()
    with TestClient(app) as client:
        with client.websocket_connect('/ws/device') as ws:
            hello(ws)
            assert ws.receive_json()['code']=='heartbeat_timeout'
        assert client.get('/api/face/devices').json()[0]['connected'] is False
