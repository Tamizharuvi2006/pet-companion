import pytest

from app.core.config import get_settings
from app.services.whisper_service import WhisperService


@pytest.fixture(autouse=True)
def avoid_loading_whisper_models_in_api_tests(monkeypatch: pytest.MonkeyPatch):
    """Keep API lifecycle tests offline and avoid holding two models in RAM."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()

    async def skip_model_load(_self: WhisperService) -> None:
        return None

    monkeypatch.setattr(WhisperService, "load", skip_model_load)
    yield
    get_settings.cache_clear()
