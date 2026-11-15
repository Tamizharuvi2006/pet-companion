import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import ai, context, memory
from app.core.schemas import ChatRequest, ChatResponse, Message
from app.memory.short_term import ShortTermMemory
from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.request_limits import CapacityExceeded

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


async def begin_turn(
    text: str,
    session_id: str | None,
    short_term: ShortTermMemory,
    context_service: ContextService,
) -> tuple[str, list[dict[str, str]]]:
    """Persist the user message and construct the provider context."""
    active_session = await short_term.session_id(session_id)
    await short_term.add(active_session, Message(role="user", content=text))
    return active_session, context_service.build_messages(await short_term.get_history(active_session))


async def finish_turn(
    session_id: str, reply: str, short_term: ShortTermMemory
) -> ChatResponse:
    await short_term.add(session_id, Message(role="assistant", content=reply))
    return ChatResponse(session_id=session_id, reply=reply)


async def generate_reply(
    text: str,
    session_id: str | None,
    short_term: ShortTermMemory,
    ai_service: AIService,
    context_service: ContextService,
) -> ChatResponse:
    active_session, messages = await begin_turn(text, session_id, short_term, context_service)
    started = perf_counter()
    try:
        reply = await ai_service.reply(messages)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    logger.info("voice_timing stage=openrouter seconds=%.3f", perf_counter() - started)
    return await finish_turn(active_session, reply, short_term)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    short_term: ShortTermMemory = Depends(memory),
    ai_service: AIService = Depends(ai),
    context_service: ContextService = Depends(context),
) -> ChatResponse:
    try:
        async with request.app.state.voice_turn_gate.slot():
            return await generate_reply(body.text, body.session_id, short_term, ai_service, context_service)
    except CapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
