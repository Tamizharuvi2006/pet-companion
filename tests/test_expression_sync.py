"""Offline canonical controller and device acknowledgment acceptance."""
import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from app.device.registry import DeviceRegistry
from app.device.face import PlaybackReport, ExpressionEvent


@pytest.mark.skipif(shutil.which('node') is None,reason='Node required')
def test_shared_browser_controller_priority_expiration_and_stale_events():
    script=r'''
global.BroadcastChannel=undefined;
const {ExpressionController}=require('./app/frontend/expression-controller.js');
const assert=require('node:assert/strict');let now=0,seq=0;
const c=new ExpressionController(()=>now);
const event=(expression,source,turn='one')=>({version:1,event_id:String(++seq),session_id:'test',turn_id:turn,destination:'browser',source,sequence:seq,expression,duration_ms:1000});
c.beginTurn('one');assert(c.apply(event('listening','conversation')));assert.equal(c.current(),'listening');
c.apply(event('happy','touch'));assert.equal(c.current(),'listening');
c.apply(event('thinking','conversation'));assert.equal(c.current(),'thinking');
c.apply(event('speaking','playback'));assert.equal(c.current(),'speaking');
const old=event('idle','playback');c.apply(old);assert.equal(c.current(),'thinking');assert(!c.apply(old));
c.apply(event('idle','conversation'));assert.equal(c.current(),'happy');now=1100;assert.equal(c.current(),'idle');
c.beginTurn('two');assert(!c.apply(event('speaking','playback','one')));assert(!c.beginTurn('one'));
c.apply(event('offline','connectivity','two'));assert.equal(c.current(),'offline');
c.apply(event('error','error','two'));assert.equal(c.current(),'error');now=2200;assert.equal(c.current(),'offline');c.apply(event('idle','connectivity','two'));assert.equal(c.current(),'idle');
console.log('controller acceptance passed');
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def report(event,turn=1,sequence=1,basis='simulated_dma'):
    return PlaybackReport(event=event,turn_id=turn,sequence=sequence,basis=basis,estimated=True)


def test_server_send_is_not_playback_and_old_turn_cannot_complete_new_one():
    async def run():
        registry=DeviceRegistry();await registry.connected('bella','test',{}, {})
        await registry.begin_playback('bella',1)
        assert not await registry.playback_report('bella',report('playback_drained'))
        await registry.audio_sent('bella',1)
        record=(await registry.snapshot('bella'))[0]
        assert record['server_audio_complete'] and record['playback_status']=='server_sent'
        assert await registry.playback_report('bella',report('playback_started'))
        assert not await registry.playback_report('bella',report('playback_started'))
        assert await registry.playback_report('bella',report('playback_drained',sequence=2))
        assert not await registry.playback_report('bella',report('playback_started',sequence=3))
        await registry.begin_playback('bella',2)
        assert not await registry.playback_report('bella',report('playback_drained',sequence=4))
        await registry.cancel_playback('bella')
        assert not await registry.playback_report('bella',report('playback_drained',turn=2,sequence=5))
        assert await registry.playback_report('bella',report('playback_interrupted',turn=2,sequence=6))
        await registry.disconnected('bella');await registry.connected('bella','new',{}, {})
        assert not await registry.playback_report('bella',report('playback_started',turn=2,sequence=7))
    asyncio.run(run())


def test_acknowledgment_deadlines_and_metadata_validation():
    async def run():
        registry=DeviceRegistry();await registry.connected('bella','test',{'face_protocol_v1':True},{})
        command=await registry.command('bella','happy',1800)
        registry._command_deadlines['bella']=0
        await registry.acknowledge('bella',command)
        assert (await registry.snapshot('bella'))[0]['command_status']=='ack_timeout'
        await registry.begin_playback('bella',1);registry._playback_deadlines['bella']=0
        assert (await registry.snapshot('bella'))[0]['playback_status']=='ack_timeout'
    asyncio.run(run())
    with pytest.raises(ValueError):
        ExpressionEvent(event_id='test',session_id='session',destination='device',source='gpio',expression='idle',sequence=1,priority=1,duration_ms=1000)


@pytest.mark.parametrize('changes',[{'event':'playback_drained','basis':'i2s_write_accepted'},{'estimated':False},{'sequence':-1}])
def test_rejects_invalid_playback_evidence(changes):
    data={'event':'playback_started','turn_id':1,'sequence':1,'basis':'i2s_write_accepted','estimated':True}
    data.update(changes)
    with pytest.raises(ValueError):PlaybackReport.model_validate(data)


def test_railway_configuration_remains_single_process_and_secret_safe():
    root=Path(__file__).resolve().parents[1]
    docker=(root/'Dockerfile').read_text()
    assert '--workers 1' in docker and '--host 0.0.0.0' in docker and '${PORT:-8000}' in docker
    assert 'ENVIRONMENT=production' in docker
    assert 'WHISPER_PRELOAD_ENABLED=false' in docker
    assert 'WHISPER_INTERIM_ENABLED=false' in docker
    ignored=(root/'.dockerignore').read_text().splitlines()
    assert '.env' in ignored and 'firmware/' in ignored


def test_native_face_and_dma_fence_models(tmp_path):
    import os
    root=Path(__file__).resolve().parents[1]
    compiler=shutil.which('g++')
    if compiler:
        output=tmp_path/'face-test'
        subprocess.run([compiler,'-std=c++17','-I',str(root/'firmware/bella_esp32/include'),str(root/'tests/native/test_face_playback.cpp'),'-o',str(output)],check=True,capture_output=True)
        subprocess.run([str(output)],check=True,capture_output=True)
    elif os.name=='nt' and shutil.which('wsl.exe'):
        def linux(path):return subprocess.check_output(['wsl.exe','--exec','wslpath','-a',str(path)],text=True,timeout=30).strip()
        output=linux(tmp_path/'face-test')
        subprocess.run(['wsl.exe','--exec','g++','-std=c++17','-I',linux(root/'firmware/bella_esp32/include'),linux(root/'tests/native/test_face_playback.cpp'),'-o',output],check=True,capture_output=True,timeout=60)
        subprocess.run(['wsl.exe','--exec',output],check=True,capture_output=True,timeout=15)
    else:pytest.skip('A native C++ compiler is required')


def test_native_face_renderer_touch_url_and_camera_policies(tmp_path):
    root=Path(__file__).resolve().parents[1]
    sources=[root/'tests/native/test_face_renderer_and_touch.cpp',root/'tests/native/test_backend_url_policy.cpp',root/'tests/native/test_servo_safety.cpp',root/'tests/native/test_camera_provisioning_policy.cpp']
    include_dirs=[root/'firmware/bella_esp32/include',root/'firmware/bella_esp32_cam/include']
    compiler=shutil.which('g++')
    if compiler:
        for index,source in enumerate(sources):
            output=tmp_path/f'native-{index}'
            command=[compiler,'-std=c++17']
            for include_dir in include_dirs:command.extend(['-I',str(include_dir)])
            command.extend([str(source),'-o',str(output)])
            subprocess.run(command,check=True,capture_output=True)
            subprocess.run([str(output)],check=True,capture_output=True)
    elif shutil.which('wsl.exe'):
        def linux(path):return subprocess.check_output(['wsl.exe','--exec','wslpath','-a',str(path)],text=True,timeout=30).strip()
        for index,source in enumerate(sources):
            output=linux(tmp_path/f'native-{index}')
            command=['wsl.exe','--exec','g++','-std=c++17']
            for include_dir in include_dirs:command.extend(['-I',linux(include_dir)])
            command.extend([linux(source),'-o',output])
            subprocess.run(command,check=True,capture_output=True,timeout=60)
            subprocess.run(['wsl.exe','--exec',output],check=True,capture_output=True,timeout=15)
    else:pytest.skip('A native C++ compiler is required')

    unsafe_source=root/'tests/native/test_servo_safety.cpp'
    if compiler:
        rejected=subprocess.run([compiler,'-std=c++17','-I',str(root/'firmware/bella_esp32/include'),'-DBELLA_SERVO_ENABLED=1','-DBELLA_SERVO2_GPIO12_ENABLED=1',str(unsafe_source),'-o',str(tmp_path/'unsafe-servo')],capture_output=True,text=True)
    else:
        rejected=subprocess.run(['wsl.exe','--exec','g++','-std=c++17','-I',linux(root/'firmware/bella_esp32/include'),'-DBELLA_SERVO_ENABLED=1','-DBELLA_SERVO2_GPIO12_ENABLED=1',linux(unsafe_source),'-o',linux(tmp_path/'unsafe-servo')],capture_output=True,text=True,timeout=60)
    assert rejected.returncode != 0
    assert 'GPIO12 Servo 2 requires exact board/flash and reset-pull verification first' in rejected.stderr

    snapshot_source=root/'tests/native/render_face_snapshots.cpp'
    snapshot_output=tmp_path/'render-snapshots'
    snapshot_output.mkdir()
    if compiler:
        executable=tmp_path/'render-face-snapshots'
        subprocess.run([compiler,'-std=c++17','-I',str(root/'firmware/bella_esp32/include'),str(snapshot_source),'-o',str(executable)],check=True,capture_output=True)
        subprocess.run([str(executable),str(snapshot_output)],check=True,capture_output=True)
    else:
        executable=linux(tmp_path/'render-face-snapshots')
        subprocess.run(['wsl.exe','--exec','g++','-std=c++17','-I',linux(root/'firmware/bella_esp32/include'),linux(snapshot_source),'-o',executable],check=True,capture_output=True,timeout=60)
        subprocess.run(['wsl.exe','--exec',executable,linux(snapshot_output)],check=True,capture_output=True,timeout=15)
    snapshots=list(snapshot_output.glob('*.ppm'))
    assert len(snapshots)==15
    assert all(item.stat().st_size==15+240*240*3 for item in snapshots)


def test_authenticated_device_synthetic_turn_and_playback_ack(monkeypatch,tmp_path):
    import struct
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.device.websocket import router
    from app.device.http import router as http_router
    from app.device.protocol import pack_audio_frame, AUDIO_TYPE_MICROPHONE, AUDIO_TYPE_SPEAKER
    from app.services.request_limits import SlidingWindowRateLimiter
    from app.memory.short_term import ShortTermMemory
    from app.services.context_service import ContextService
    from app.services.tts_service import TTSAudioChunk
    class FakeSTT:
        async def transcribe(self,*args,**kwargs):return 'Hello Bella'
    class FakeAI:
        async def stream_reply(self,*args):yield 'Hello there, my lovely friend!'
    class FakeTTS:
        async def stream_audio(self,*args,**kwargs):yield TTSAudioChunk(provider='synthetic',data=b'offline')
    async def synthetic_pcm(ws,chunks,*,turn_id,chunk_id,send_lock,**kwargs):
        async for _ in chunks:pass
        async with send_lock:
            await ws.send_json({'type':'tts_chunk_start','version':1,'turn_id':turn_id,'chunk_id':chunk_id})
            await ws.send_bytes(pack_audio_frame(AUDIO_TYPE_SPEAKER,turn_id,0,b'\x01\x00'*640))
            await ws.send_json({'type':'tts_chunk_end','version':1,'turn_id':turn_id,'frame_count':1})
        return 1280
    monkeypatch.setattr('app.device.websocket.stream_mp3_chunks_as_pcm',synthetic_pcm)
    test_app=FastAPI();test_app.state.settings=Settings(device_auth_tokens={'bella':'offline-token-123456789'},storage_dir=tmp_path,voice_engine_default='current')
    test_app.state.device_registry=DeviceRegistry();test_app.state.rate_limiter=SlidingWindowRateLimiter()
    test_app.state.whisper=FakeSTT();test_app.state.ai=FakeAI();test_app.state.tts=FakeTTS()
    test_app.state.memory=ShortTermMemory();test_app.state.context=ContextService()
    test_app.include_router(router);test_app.include_router(http_router)
    with TestClient(test_app) as client:
        with client.websocket_connect('/ws/device') as ws:
            ws.send_json({'type':'hello','version':1,'device_id':'bella','token':'offline-token-123456789'})
            assert ws.receive_json()['type']=='device_ready'
            ws.send_json({'type':'recording_start','version':1,'turn_id':1,'sample_rate_hz':16000,'channels':1,'bits_per_sample':16,'codec':'pcm_s16le'})
            ws.send_bytes(pack_audio_frame(AUDIO_TYPE_MICROPHONE,1,0,struct.pack('<h',1000)*640))
            ws.send_json({'type':'recording_end','version':1,'turn_id':1})
            events=[]
            for _ in range(20):
                message=ws.receive()
                if message.get('text'):
                    import json
                    control=json.loads(message['text']);events.append(control['type'])
                    if control['type']=='turn_complete':break
            assert 'tts_chunk_end' in events and events[-1]=='turn_complete'
            headers={'Authorization':'Bearer offline-token-123456789'}
            assert client.get('/api/device/bella/status',headers=headers).json()['server_audio_complete']
            for seq,event in enumerate(['playback_started','playback_drained'],1):
                ws.send_json({'type':event,'version':1,'playback_version':1,'turn_id':1,'sequence':seq,'basis':'simulated_dma','estimated':True})
                ws.send_json({'type':'ping','version':1})
                assert ws.receive_json()['type']=='pong'
                assert client.get('/api/device/bella/status',headers=headers).json()['playback_status']==event.removeprefix('playback_')
