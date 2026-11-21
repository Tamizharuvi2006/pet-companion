from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Role = Literal["user", "assistant", "system"]


class Message(BaseModel):
    role: Role
    content: str = Field(min_length=1, max_length=20_000)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    session_id: str | None = Field(default=None, max_length=128)


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    voice: str | None = Field(default=None, max_length=128)
    rate: str | None = Field(default=None, max_length=16)
    pitch: str | None = Field(default=None, max_length=16)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class AuthSessionResponse(BaseModel):
    required: bool
    authenticated: bool


class TTSResponse(BaseModel):
    audio_url: str


class TalkResponse(BaseModel):
    session_id: str
    transcript: str
    reply: str
    audio_url: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str


class ClientConfigResponse(BaseModel):
    pet_voice_synthesis_enabled: bool


class WebSocketEvent(BaseModel):
    type: str
    data: str | None = Field(default=None, max_length=1_400_000)
    session_id: str | None = Field(default=None, max_length=128)
    capture_id: str | None = Field(default=None, max_length=64)
    duration_ms: int | None = Field(default=None, ge=1, le=10_000)
    streaming_mp3: bool | None = None
    voice_engine: Literal["current", "gpt_audio_mini"] | None = None
