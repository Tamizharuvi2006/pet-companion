from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import tts
from app.core.schemas import TTSRequest, TTSResponse
from app.services.tts_service import TTSService
from app.services.request_limits import CapacityExceeded

router = APIRouter(tags=["tts"])


@router.post("/tts", response_model=TTSResponse)
async def text_to_speech(
    body: TTSRequest, request: Request, service: TTSService = Depends(tts)
) -> TTSResponse:
    try:
        async with request.app.state.voice_turn_gate.slot():
            return TTSResponse(
                audio_url=await service.synthesize(
                    body.text,
                    voice=body.voice,
                    rate=body.rate,
                    pitch=body.pitch,
                )
            )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except CapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
