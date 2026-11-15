from fastapi import Depends, HTTPException, Request, status

from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.openrouter_stt_service import OpenRouterSTTService
from app.services.tts_service import TTSService
from app.memory.short_term import ShortTermMemory
from app.services.browser_security import browser_principal


def browser_user(request: Request) -> str:
    return browser_principal(request)


async def enforce_rate_limit(
    request: Request,
    principal: str,
    operation: str,
    limit: int,
) -> str:
    allowed = await request.app.state.rate_limiter.allow(
        f"{operation}:{principal}", limit
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request limit reached; try again shortly",
            headers={"Retry-After": "60"},
        )
    return principal


def memory(request: Request) -> ShortTermMemory:
    return request.app.state.memory


def ai(request: Request) -> AIService:
    return request.app.state.ai


def context(request: Request) -> ContextService:
    return request.app.state.context


def tts(request: Request) -> TTSService:
    return request.app.state.tts


def whisper(request: Request) -> OpenRouterSTTService:
    return request.app.state.whisper
