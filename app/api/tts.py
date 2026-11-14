from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import tts
from app.core.schemas import TTSRequest, TTSResponse
from app.services.tts_service import TTSService

router = APIRouter(tags=["tts"])


@router.post("/tts", response_model=TTSResponse)
async def text_to_speech(
    body: TTSRequest, service: TTSService = Depends(tts)
) -> TTSResponse:
    try:
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
