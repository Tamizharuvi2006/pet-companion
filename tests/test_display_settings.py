import pytest

from app.core.config import Settings
from app.device.display_settings import parse_caption_toggle


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("turn captions on", True),
        ("show the captions please", True),
        ("show text", True),
        ("hide subtitles", False),
        ("no captions", False),
        ("face only", False),
        ("only eyes", False),
        ("turn the display off", None),
        ("how are you, Bella?", None),
    ],
)
def test_caption_voice_commands_are_explicit(text: str, expected: bool | None) -> None:
    assert parse_caption_toggle(text) is expected


def test_gpt_audio_mini_is_the_default_voice_engine() -> None:
    assert Settings().voice_engine_default == "gpt_audio_mini"
