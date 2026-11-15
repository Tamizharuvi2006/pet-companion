"""Single-owner dashboard: all authenticated browser sessions share one robot."""
from fastapi import APIRouter, HTTPException, Request
from app.device.face import FaceCommand
from app.services.browser_security import browser_principal

router = APIRouter(prefix='/api/face', tags=['face'])


@router.get('/devices')
async def devices(request: Request) -> list[dict]:
    browser_principal(request)
    # Only provisioned devices are visible; never expose credentials.
    permitted = request.app.state.settings.device_auth_tokens
    return [record for record in await request.app.state.device_registry.snapshot()
            if record['device_id'] in permitted]


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
