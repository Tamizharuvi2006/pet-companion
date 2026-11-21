"""Single-owner dashboard: all authenticated browser sessions share one robot."""
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.device.face import FaceCommand
from app.device.doctor import build_hardware_doctor
from app.services.browser_security import browser_principal

router = APIRouter(prefix='/api/face', tags=['face'])
logger = logging.getLogger(__name__)


@router.get('/devices')
async def devices(request: Request) -> list[dict]:
    browser_principal(request)
    # Only provisioned devices are visible; never expose credentials.
    permitted = request.app.state.settings.device_auth_tokens
    return [record for record in await request.app.state.device_registry.snapshot()
            if record['device_id'] in permitted]


@router.get('/devices/doctor')
async def device_doctor(request: Request) -> list[dict]:
    browser_principal(request)
    permitted = request.app.state.settings.device_auth_tokens
    records = {record['device_id']: record for record in await request.app.state.device_registry.snapshot()
               if record['device_id'] in permitted}
    return [build_hardware_doctor(records.get(device_id), device_id) for device_id in sorted(permitted)]


@router.post('/{device_id}/expression', status_code=202)
async def expression(device_id: str, body: FaceCommand, request: Request) -> dict:
    principal = browser_principal(request)
    if device_id not in request.app.state.settings.device_auth_tokens:
        raise HTTPException(404, 'Device not available')
    if not await request.app.state.rate_limiter.allow(f'face:{principal}', 30):
        raise HTTPException(429, 'Face command rate limit reached')
    command_id = await request.app.state.device_registry.command(device_id, body.expression, body.duration_ms)
    if command_id is None:
        raise HTTPException(409, 'Device offline or face protocol unavailable')
    return {'command_id': command_id, 'status': 'pending', 'physical_delivery_confirmed': False}


@router.post('/{device_id}/camera/capture', response_class=Response)
async def capture_camera(device_id: str, request: Request) -> Response:
    """One explicitly requested camera frame; URL and token come only from server config."""
    principal = browser_principal(request)
    settings = request.app.state.settings
    if device_id not in settings.device_auth_tokens:
        raise HTTPException(404, 'Device not available')
    if not settings.camera_transport_ready:
        raise HTTPException(503, 'Optional camera is not configured with an approved transport')
    if not await request.app.state.rate_limiter.allow(f'camera:{principal}', 3):
        raise HTTPException(429, 'Camera capture rate limit reached')
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=2.0), follow_redirects=False) as client:
            async with client.stream(
                'GET', settings.camera_base_url.rstrip('/') + '/snapshot',
                headers={'Authorization': f'Bearer {settings.camera_token}'},
            ) as upstream:
                upstream.raise_for_status()
                if upstream.headers.get('content-type', '').split(';')[0].lower() != 'image/jpeg':
                    raise HTTPException(502, 'Camera did not return a JPEG')
                image = bytearray()
                async for block in upstream.aiter_bytes(16 * 1024):
                    image.extend(block)
                    if len(image) > settings.device_max_image_bytes:
                        raise HTTPException(413, 'Camera image exceeds the configured limit')
    except HTTPException:
        raise
    except httpx.HTTPError as error:
        logger.warning('Authorized camera capture failed: %s', type(error).__name__)
        raise HTTPException(502, 'Camera is unreachable from the backend network') from error
    if not image.startswith(b'\xff\xd8\xff'):
        raise HTTPException(502, 'Camera response is not a valid JPEG')
    await request.app.state.device_registry.camera_snapshot(device_id, len(image))
    return Response(bytes(image), media_type='image/jpeg', headers={'Cache-Control': 'no-store'})
