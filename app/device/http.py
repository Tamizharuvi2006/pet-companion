import asyncio
import logging

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response

from app.device.security import verify_device_token
from app.device.protocol import PROTOCOL_VERSION, SAMPLE_RATE_HZ

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/device", tags=["device"])


def _authorize(request: Request, device_id: str, authorization: str | None) -> None:
    scheme, separator, token = (authorization or "").partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not verify_device_token(request.app.state.settings, device_id, token)
    ):
        raise HTTPException(status_code=401, detail="Device authentication failed")


@router.get("/{device_id}/status")
async def device_status(
    device_id: str, request: Request, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    _authorize(request, device_id, authorization)
    records = await request.app.state.device_registry.snapshot(device_id)
    if not records:
        return {"device_id": device_id, "connected": False, "state": "UNKNOWN"}
    return records[0]


@router.get("/{device_id}/config")
async def device_config(
    device_id: str, request: Request, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    _authorize(request, device_id, authorization)
    settings = request.app.state.settings
    return {
        "protocol_version": PROTOCOL_VERSION,
        "audio": {
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "channels": 1,
            "bits_per_sample": 16,
            "codec": "pcm_s16le",
            "frame_duration_ms": 40,
        },
        "max_recording_seconds": settings.device_max_recording_seconds,
        "camera_enabled": settings.camera_enabled,
    }


@router.post("/{device_id}/camera/capture", response_class=Response)
async def capture_camera(
    device_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    """Proxy one JPEG from the configured camera; callers cannot supply a URL."""
    _authorize(request, device_id, authorization)
    settings = request.app.state.settings
    if not settings.camera_enabled or not settings.camera_base_url or not settings.camera_token:
        raise HTTPException(status_code=503, detail="Camera capture is not configured")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            async with client.stream(
                "GET",
                settings.camera_base_url.rstrip("/") + "/snapshot",
                headers={"Authorization": f"Bearer {settings.camera_token}"},
            ) as upstream:
                upstream.raise_for_status()
                if upstream.headers.get("content-type", "").split(";")[0].lower() != "image/jpeg":
                    raise HTTPException(status_code=502, detail="Camera did not return a JPEG")
                content_length = int(upstream.headers.get("content-length", "0") or "0")
                if content_length > settings.device_max_image_bytes:
                    raise HTTPException(status_code=413, detail="Camera image exceeds the configured limit")
                image = bytearray()
                async for block in upstream.aiter_bytes(16 * 1024):
                    image.extend(block)
                    if len(image) > settings.device_max_image_bytes:
                        raise HTTPException(status_code=413, detail="Camera image exceeds the configured limit")
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Configured camera capture failed: %s", type(error).__name__)
        raise HTTPException(status_code=502, detail="Camera is unreachable") from error

    if not image.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=502, detail="Camera response is not a valid JPEG")
    await request.app.state.device_registry.camera_snapshot(device_id, len(image))
    return Response(
        content=bytes(image),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Bella-Device": device_id},
    )
