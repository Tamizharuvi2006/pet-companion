"""Versioned compact face contract; never dispatches voice or movement."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Expression = Literal['idle', 'happy', 'love', 'excited', 'curious', 'surprised', 'sad', 'angry', 'sleepy', 'wink', 'listening', 'thinking', 'speaking', 'offline', 'error']
TOUCH_EXPRESSIONS = ('happy', 'love', 'curious', 'wink')


class FaceCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expression: Expression
    duration_ms: int = Field(default=1800, ge=250, le=5000, strict=True)


class FaceReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expression: Expression
    sequence: int = Field(ge=0, le=0xFFFFFFFF, strict=True)
    touch_pad: int | None = Field(default=None, ge=1, le=4, strict=True)
