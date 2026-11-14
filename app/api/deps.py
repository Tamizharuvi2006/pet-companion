from fastapi import Request

from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.openrouter_stt_service import OpenRouterSTTService
from app.services.tts_service import TTSService
from app.memory.short_term import ShortTermMemory


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
