"""Voice commands for the on-device reply-caption overlay."""

import re
import unicodedata


def parse_caption_toggle(text: str) -> bool | None:
    """Return a requested caption state, or None for ordinary speech.

    Deliberately require an explicit caption/text/face target so ordinary uses
    of words like "show" or "off" do not unexpectedly change the display.
    """
    normalized = unicodedata.normalize("NFKC", text).casefold()
    words = re.findall(r"[\w]+", normalized, flags=re.UNICODE)
    if not words:
        return None
    phrase = " ".join(words)
    target = any(word in words for word in ("caption", "captions", "subtitle", "subtitles"))
    target = target or any(
        marker in phrase
        for marker in ("screen text", "display text", "show text", "hide text", "text on", "text off")
    )
    only_face = any(
        marker in phrase
        for marker in ("only face", "face only", "only eyes", "eyes only", "face animation only")
    )
    if only_face:
        return False
    if not target:
        return None

    if any(word in words for word in ("off", "hide", "disable", "disabled", "remove", "no")):
        return False
    if any(word in words for word in ("on", "show", "enable", "enabled", "display")):
        return True
    return None
