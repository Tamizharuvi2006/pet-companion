import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    """Runtime settings, loaded from environment variables or .env."""

    app_name: str = "Bella AI Cloud"
    environment: str = "development"
    openrouter_api_key: str | None = None
    model_name: str = "openai/gpt-4o-mini"
    max_tokens: int = 80
    whisper_model: str = "base"
    whisper_interim_model: str = "tiny"
    whisper_device: str = "cpu"
    whisper_language: str | None = None
    whisper_final_beam_size: int = 2
    whisper_interim_beam_size: int = 1
    openrouter_stt_enabled: bool = True
    openrouter_stt_model: str = "openai/whisper-large-v3-turbo"
    openrouter_tanglish_stt_model: str = "mistralai/voxtral-mini-transcribe"
    openrouter_tts_enabled: bool = True
    openrouter_tts_model: str = "hexgrad/kokoro-82m"
    openrouter_tts_voice: str = "af_bella"
    openrouter_tts_cute_voice: str = "af_bella"
    openrouter_timeout_seconds: float = 60.0
    openrouter_tts_timeout_seconds: float = 8.0
    tts_provider: str = "kokoro"
    tts_race_enabled: bool = True
    tts_first_chunk_words: int = Field(default=6, ge=4, le=8)
    tts_voice: str = "en-US-AnaNeural"
    device_auth_tokens: dict[str, str] = Field(default_factory=dict)
    device_max_recording_seconds: int = Field(default=15, ge=1, le=60)
    device_max_audio_frame_bytes: int = Field(default=2048, ge=1280, le=2048)
    device_max_image_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)
    camera_enabled: bool = False
    camera_base_url: str | None = None
    camera_token: str | None = None
    port: int = 8000
    max_history_messages: int = 20
    max_upload_bytes: int = 25 * 1024 * 1024
    storage_dir: Path = Path("app/storage")

    @property
    def audio_dir(self) -> Path:
        return self.storage_dir / "audio"

    @property
    def upload_dir(self) -> Path:
        return self.storage_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    """Create typed settings from Railway/Docker/local environment variables."""
    device_auth_tokens: dict[str, str] = {}
    for item in os.getenv("BELLA_DEVICE_TOKENS", "").split(","):
        device_id, separator, token = item.partition("=")
        if separator and device_id.strip() and token.strip():
            device_auth_tokens[device_id.strip()] = token.strip()

    return Settings(
        app_name=os.getenv("APP_NAME", "Bella AI Cloud"),
        environment=os.getenv("ENVIRONMENT", "development"),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
        model_name=os.getenv("MODEL_NAME", "openai/gpt-4o-mini"),
        max_tokens=int(os.getenv("MAX_TOKENS", "80")),
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        whisper_interim_model=os.getenv("WHISPER_INTERIM_MODEL", "tiny"),
        whisper_device=os.getenv("WHISPER_DEVICE", "cpu"),
        whisper_language=os.getenv("WHISPER_LANGUAGE", "") or None,
        whisper_final_beam_size=int(os.getenv("WHISPER_FINAL_BEAM_SIZE", "2")),
        whisper_interim_beam_size=int(os.getenv("WHISPER_INTERIM_BEAM_SIZE", "1")),
        openrouter_stt_enabled=os.getenv("OPENROUTER_STT_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"},
        openrouter_stt_model=os.getenv(
            "OPENROUTER_STT_MODEL", "openai/whisper-large-v3-turbo"
        ),
        openrouter_tanglish_stt_model=os.getenv(
            "OPENROUTER_TANGLISH_STT_MODEL", "mistralai/voxtral-mini-transcribe"
        ),
        openrouter_tts_enabled=os.getenv("OPENROUTER_TTS_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"},
        openrouter_tts_model=os.getenv("OPENROUTER_TTS_MODEL", "hexgrad/kokoro-82m"),
        openrouter_tts_voice=os.getenv("OPENROUTER_TTS_VOICE", "af_bella"),
        openrouter_tts_cute_voice=os.getenv("OPENROUTER_TTS_CUTE_VOICE", "af_bella"),
        openrouter_timeout_seconds=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "60")),
        openrouter_tts_timeout_seconds=float(
            os.getenv("OPENROUTER_TTS_TIMEOUT_SECONDS", "8")
        ),
        tts_provider=os.getenv("TTS_PROVIDER", "kokoro").lower(),
        tts_race_enabled=os.getenv("TTS_RACE_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"},
        tts_first_chunk_words=int(os.getenv("TTS_FIRST_CHUNK_WORDS", "6")),
        tts_voice=os.getenv("TTS_VOICE", "en-US-AnaNeural"),
        device_auth_tokens=device_auth_tokens,
        device_max_recording_seconds=int(os.getenv("DEVICE_MAX_RECORDING_SECONDS", "15")),
        device_max_audio_frame_bytes=int(os.getenv("DEVICE_MAX_AUDIO_FRAME_BYTES", "2048")),
        device_max_image_bytes=int(os.getenv("DEVICE_MAX_IMAGE_BYTES", "1000000")),
        camera_enabled=os.getenv("BELLA_CAMERA_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"},
        camera_base_url=os.getenv("BELLA_CAMERA_BASE_URL") or None,
        camera_token=os.getenv("BELLA_CAMERA_TOKEN") or None,
        port=int(os.getenv("PORT", "8000")),
        max_history_messages=int(os.getenv("MAX_HISTORY_MESSAGES", "20")),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
        storage_dir=Path(os.getenv("STORAGE_DIR", "app/storage")),
    )
