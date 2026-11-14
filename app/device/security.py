import hmac

from app.core.config import Settings


def verify_device_token(settings: Settings, device_id: str, token: str) -> bool:
    """Compare the first-message token in constant time; never use URL credentials."""
    expected = settings.device_auth_tokens.get(device_id)
    return bool(expected) and hmac.compare_digest(expected.encode(), token.encode())
