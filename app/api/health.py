from fastapi import APIRouter, Request

from app.core.schemas import ClientConfigResponse, HealthResponse
from app.services.browser_security import browser_principal

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(status="ok", service=settings.app_name, environment=settings.environment)


@router.get("/client-config", response_model=ClientConfigResponse)
async def client_config(request: Request) -> ClientConfigResponse:
    """Expose only whether pet TTS is safe for the current browser session."""
    browser_principal(request)
    settings = request.app.state.settings
    return ClientConfigResponse(
        pet_voice_synthesis_enabled=not settings.voice_test_enabled
    )
