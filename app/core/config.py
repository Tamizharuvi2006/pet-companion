import ipaddress
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    """Runtime settings, loaded from environment variables or .env."""

    app_name: str = "Bella AI Cloud"
    environment: str = "development"
    openrouter_api_key: str | None = None
    browser_access_password: str | None = None
    browser_session_secret: str | None = None
    browser_allowed_origins: tuple[str, ...] = ()
    browser_session_ttl_seconds: int = Field(default=86_400, ge=300, le=2_592_000)
    login_attempts_per_minute: int = Field(default=8, ge=1, le=100)
    chat_requests_per_minute: int = Field(default=20, ge=1, le=600)
    stt_requests_per_minute: int = Field(default=12, ge=1, le=600)
    tts_requests_per_minute: int = Field(default=20, ge=1, le=600)
    talk_requests_per_minute: int = Field(default=8, ge=1, le=600)
    voice_requests_per_minute: int = Field(default=10, ge=1, le=600)
    max_concurrent_provider_requests: int = Field(default=4, ge=1, le=64)
    max_active_browser_websockets: int = Field(default=8, ge=1, le=256)
    max_active_recordings: int = Field(default=2, ge=1, le=64)
    max_active_voice_turns: int = Field(default=4, ge=1, le=64)
    max_ws_audio_frame_bytes: int = Field(default=65_536, ge=1_280, le=1_048_576)
    max_ws_recording_bytes: int = Field(default=8 * 1024 * 1024, ge=65_536, le=100 * 1024 * 1024)
    max_ws_recording_seconds: int = Field(default=30, ge=1, le=300)
    model_name: str = "openai/gpt-4o-mini"
    voice_audio_input_enabled: bool = False
    voice_engine_default: Literal["current", "gpt_audio_mini"] = "gpt_audio_mini"
    voice_audio_model: str = "openai/gpt-audio-mini"
    voice_audio_voice: str = "shimmer"
    voice_audio_max_tokens: int = Field(default=512, ge=64, le=4096)
    max_tokens: int = 80
    whisper_model: str = "base"
    whisper_preload_enabled: bool = True
    whisper_interim_model: str = "tiny"
    whisper_interim_enabled: bool = True
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
    tts_race_enabled: bool = False
    tts_first_chunk_words: int = Field(default=5, ge=4, le=8)
    voice_diagnostic_mode: bool = False
    bounded_full_voice_test: bool = False
    tts_voice: str = "en-US-AnaNeural"
    device_auth_tokens: dict[str, str] = Field(default_factory=dict)
    device_auth_required: bool = True
    device_max_recording_seconds: int = Field(default=15, ge=1, le=60)
    device_max_audio_frame_bytes: int = Field(default=2048, ge=1280, le=2048)
    device_max_image_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)
    camera_enabled: bool = False
    camera_base_url: str | None = None
    camera_token: str | None = None
    render_keepalive_interval_seconds: int = Field(default=0, ge=0, le=3600)
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

    @property
    def public_mode(self) -> bool:
        return self.environment.strip().lower() not in {"development", "dev", "local", "test"}

    @property
    def camera_transport_ready(self) -> bool:
        """A public deployment must never send the camera bearer token over plain HTTP."""
        if not self.camera_enabled or not self.camera_base_url or not self.camera_token:
            return False
        try:
            parsed = urlsplit(self.camera_base_url)
            # Accessing .port also validates malformed port strings.
            _ = parsed.port
        except ValueError:
            return False
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or len(self.camera_token) < 16
        ):
            return False
        if parsed.scheme.lower() == "https":
            return True
        if self.public_mode or parsed.scheme.lower() != "http":
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith((".local", ".lan", ".home.arpa")):
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return address.is_private or address.is_loopback or address.is_link_local

    @property
    def voice_test_enabled(self) -> bool:
        return self.voice_diagnostic_mode or self.bounded_full_voice_test

    @property
    def voice_test_mode(self) -> str:
        if self.bounded_full_voice_test:
            return "bounded_full_voice_test"
        if self.voice_diagnostic_mode:
            return "first_phrase_diagnostic"
        return "disabled"

    def validate_public_security(self) -> None:
        if self.camera_enabled and not self.camera_transport_ready:
            raise RuntimeError(
                "Enabled camera requires a valid base URL and 16+ character token; public mode requires HTTPS."
            )
        if not self.public_mode:
            return
        if not self.browser_access_password or len(self.browser_access_password) < 16:
            raise RuntimeError("Public browser authentication requires BELLA_ACCESS_PASSWORD (16+ characters).")
        if not self.browser_session_secret or len(self.browser_session_secret) < 32:
            raise RuntimeError("Public browser authentication requires BELLA_SESSION_SECRET (32+ characters).")
        if not self.browser_allowed_origins:
            raise RuntimeError("Public browser authentication requires BELLA_ALLOWED_ORIGINS.")
        for origin in self.browser_allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme.lower() != "https"
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise RuntimeError(
                    "Public browser origins must be exact HTTPS origins without paths or credentials."
                )

    def validate_voice_diagnostic(self) -> None:
        """Fail closed unless the one-turn diagnostic uses its authorized providers."""
        if self.voice_diagnostic_mode and self.bounded_full_voice_test:
            raise RuntimeError(
                "Enable only one voice test mode: VOICE_DIAGNOSTIC_MODE or BOUNDED_FULL_VOICE_TEST."
            )
        if not self.voice_test_enabled:
            return
        if not self.openrouter_api_key:
            raise RuntimeError("Voice test mode requires OPENROUTER_API_KEY.")
        if not self.openrouter_stt_enabled or not self.openrouter_tts_enabled:
            raise RuntimeError("Voice test mode requires OpenRouter STT and Kokoro enabled.")
        if self.whisper_interim_enabled:
            raise RuntimeError(
                "Voice test mode requires WHISPER_INTERIM_ENABLED=false."
            )
        if self.tts_race_enabled:
            raise RuntimeError("Voice test mode requires TTS_RACE_ENABLED=false.")
        required_values = {
            "MODEL_NAME": (self.model_name, "openai/gpt-4o-mini"),
            "OPENROUTER_STT_MODEL": (
                self.openrouter_stt_model,
                "openai/whisper-large-v3-turbo",
            ),
            "OPENROUTER_TTS_MODEL": (self.openrouter_tts_model, "hexgrad/kokoro-82m"),
            "OPENROUTER_TTS_VOICE": (self.openrouter_tts_voice, "af_bella"),
            "TTS_PROVIDER": (self.tts_provider, "kokoro"),
        }
        mismatches = [
            name for name, (actual, expected) in required_values.items() if actual != expected
        ]
        if mismatches:
            raise RuntimeError(
                "Voice diagnostic mode requires the approved GPT-4o Mini, Whisper Large V3 Turbo, "
                "and Kokoro af_bella settings; mismatch: " + ", ".join(mismatches)
            )


@lru_cache
def get_settings() -> Settings:
    """Create typed settings from Render/Docker/local environment variables."""
    device_auth_tokens: dict[str, str] = {}
    for item in os.getenv("BELLA_DEVICE_TOKENS", "").split(","):
        device_id, separator, token = item.partition("=")
        if separator and device_id.strip() and token.strip():
            device_auth_tokens[device_id.strip()] = token.strip()

    return Settings(
        app_name=os.getenv("APP_NAME", "Bella AI Cloud"),
        environment=os.getenv("ENVIRONMENT", "development"),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
        browser_access_password=os.getenv("BELLA_ACCESS_PASSWORD") or None,
        browser_session_secret=os.getenv("BELLA_SESSION_SECRET") or None,
        browser_allowed_origins=tuple(
            origin.strip().rstrip("/")
            for origin in os.getenv("BELLA_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        ),
        browser_session_ttl_seconds=int(os.getenv("BELLA_SESSION_TTL_SECONDS", "86400")),
        login_attempts_per_minute=int(os.getenv("LOGIN_ATTEMPTS_PER_MINUTE", "8")),
        chat_requests_per_minute=int(os.getenv("CHAT_REQUESTS_PER_MINUTE", "20")),
        stt_requests_per_minute=int(os.getenv("STT_REQUESTS_PER_MINUTE", "12")),
        tts_requests_per_minute=int(os.getenv("TTS_REQUESTS_PER_MINUTE", "20")),
        talk_requests_per_minute=int(os.getenv("TALK_REQUESTS_PER_MINUTE", "8")),
        voice_requests_per_minute=int(os.getenv("VOICE_REQUESTS_PER_MINUTE", "10")),
        max_concurrent_provider_requests=int(os.getenv("MAX_CONCURRENT_PROVIDER_REQUESTS", "4")),
        max_active_browser_websockets=int(os.getenv("MAX_ACTIVE_BROWSER_WEBSOCKETS", "8")),
        max_active_recordings=int(os.getenv("MAX_ACTIVE_RECORDINGS", "2")),
        max_active_voice_turns=int(os.getenv("MAX_ACTIVE_VOICE_TURNS", "4")),
        max_ws_audio_frame_bytes=int(os.getenv("MAX_WS_AUDIO_FRAME_BYTES", "65536")),
        max_ws_recording_bytes=int(os.getenv("MAX_WS_RECORDING_BYTES", str(8 * 1024 * 1024))),
        max_ws_recording_seconds=int(os.getenv("MAX_WS_RECORDING_SECONDS", "30")),
        model_name=os.getenv("MODEL_NAME", "openai/gpt-4o-mini"),
        voice_audio_input_enabled=os.getenv("VOICE_AUDIO_INPUT_ENABLED", "false").lower() in {'1', 'true', 'yes'},
        voice_engine_default=os.getenv("VOICE_ENGINE_DEFAULT", "gpt_audio_mini").strip().lower(),
        voice_audio_model=os.getenv("VOICE_AUDIO_MODEL", "openai/gpt-audio-mini"),
        voice_audio_voice=os.getenv("VOICE_AUDIO_VOICE", "shimmer"),
        voice_audio_max_tokens=int(os.getenv("VOICE_AUDIO_MAX_TOKENS", "512")),
        max_tokens=int(os.getenv("MAX_TOKENS", "80")),
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        whisper_preload_enabled=os.getenv("WHISPER_PRELOAD_ENABLED", "true").lower() in {'1', 'true', 'yes', 'on'},
        whisper_interim_model=os.getenv("WHISPER_INTERIM_MODEL", "tiny"),
        whisper_interim_enabled=os.getenv("WHISPER_INTERIM_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"},
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
        tts_race_enabled=os.getenv("TTS_RACE_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"},
        tts_first_chunk_words=int(os.getenv("TTS_FIRST_CHUNK_WORDS", "5")),
        voice_diagnostic_mode=os.getenv("VOICE_DIAGNOSTIC_MODE", "false").lower()
        in {"1", "true", "yes", "on"},
        bounded_full_voice_test=os.getenv("BOUNDED_FULL_VOICE_TEST", "false").lower()
        in {"1", "true", "yes", "on"},
        tts_voice=os.getenv("TTS_VOICE", "en-US-AnaNeural"),
        device_auth_tokens=device_auth_tokens,
        # Unknown values fail closed; only an explicit false-like value opens demo WS access.
        device_auth_required=os.getenv("BELLA_DEVICE_AUTH_REQUIRED", "true").strip().lower()
        not in {"0", "false", "no", "off"},
        device_max_recording_seconds=int(os.getenv("DEVICE_MAX_RECORDING_SECONDS", "15")),
        device_max_audio_frame_bytes=int(os.getenv("DEVICE_MAX_AUDIO_FRAME_BYTES", "2048")),
        device_max_image_bytes=int(os.getenv("DEVICE_MAX_IMAGE_BYTES", "1000000")),
        camera_enabled=os.getenv("BELLA_CAMERA_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"},
        camera_base_url=os.getenv("BELLA_CAMERA_BASE_URL") or None,
        camera_token=os.getenv("BELLA_CAMERA_TOKEN") or None,
        render_keepalive_interval_seconds=int(
            os.getenv("RENDER_KEEPALIVE_INTERVAL_SECONDS", "0")
        ),
        port=int(os.getenv("PORT", "8000")),
        max_history_messages=int(os.getenv("MAX_HISTORY_MESSAGES", "20")),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
        storage_dir=Path(os.getenv("STORAGE_DIR", "app/storage")),
    )
