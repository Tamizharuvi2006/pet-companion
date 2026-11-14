from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    body = await request.app.state.metrics.render()
    devices = await request.app.state.device_registry.snapshot()
    connected_devices = sum(1 for device in devices if device["connected"])
    return PlainTextResponse(
        body
        + "# HELP bella_devices_connected Number of connected authenticated devices.\n"
        + "# TYPE bella_devices_connected gauge\n"
        + f"bella_devices_connected {connected_devices}\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
