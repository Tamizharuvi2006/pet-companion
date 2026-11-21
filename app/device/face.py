"""Versioned compact face contract; never dispatches voice or movement."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Expression = Literal['idle', 'happy', 'love', 'excited', 'curious', 'surprised', 'sad', 'angry', 'sleepy', 'wink', 'listening', 'thinking', 'speaking', 'offline', 'error']
TOUCH_EXPRESSIONS = ('happy', 'love', 'curious', 'wink')


class ExpressionEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1] = 1
    event_id: str = Field(min_length=1, max_length=96)
    device_id: str | None = Field(default=None, max_length=64)
    turn_id: str | None = Field(default=None, max_length=96)
    session_id: str = Field(min_length=1, max_length=96)
    destination: Literal['browser', 'device', 'simulation']
    source: Literal['touch', 'preview', 'conversation', 'playback', 'connectivity', 'error']
    expression: Expression
    sequence: int = Field(ge=0, strict=True)
    priority: int = Field(ge=0, le=100)
    duration_ms: int = Field(ge=100, le=60000)
    intensity: float = Field(default=1, ge=0, le=1)


class FaceCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expression: Expression
    duration_ms: int = Field(default=1800, ge=250, le=5000, strict=True)


class FaceReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expression: Expression
    sequence: int = Field(ge=0, le=0xFFFFFFFF, strict=True)
    touch_pad: int | None = Field(default=None, ge=1, le=4, strict=True)


class PlaybackReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event: Literal['playback_started', 'playback_drained', 'playback_interrupted', 'playback_error']
    turn_id: int = Field(ge=1, le=0xFFFFFFFF, strict=True)
    sequence: int = Field(ge=0, le=0xFFFFFFFF, strict=True)
    basis: Literal['i2s_write_accepted', 'dma_ring_fence', 'cancelled', 'i2s_error', 'simulated_dma']
    estimated: StrictBool

    @model_validator(mode='after')
    def coherent_basis(self):
        allowed={'playback_started': {'i2s_write_accepted','simulated_dma'},
                 'playback_drained': {'dma_ring_fence','simulated_dma'},
                 'playback_interrupted': {'cancelled','simulated_dma'},
                 'playback_error': {'i2s_error','simulated_dma'}}
        if self.basis not in allowed[self.event]:
            raise ValueError('Playback evidence basis does not match event')
        if self.basis in {'i2s_write_accepted','dma_ring_fence','simulated_dma'} and not self.estimated:
            raise ValueError('This evidence does not establish an exact acoustic timestamp')
        return self
