"""Cookie-backed browser authentication and origin validation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket, status

from app.core.config import Settings

SESSION_COOKIE = "bella_session"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_session(settings: Settings) -> tuple[str, str, int]:
    if not settings.browser_session_secret:
        raise RuntimeError("Browser session signing is not configured")
    session_id = secrets.token_urlsafe(24)
    expires_at = int(time.time()) + settings.browser_session_ttl_seconds
    payload = f"{session_id}.{expires_at}".encode("ascii")
    signature = hmac.new(
        settings.browser_session_secret.encode("utf-8"), payload, hashlib.sha256
    ).digest()
    return f"{_b64encode(payload)}.{_b64encode(signature)}", session_id, expires_at


def verify_session(settings: Settings, token: str | None) -> str | None:
    if not token or not settings.browser_session_secret:
        return None
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = _b64decode(encoded_payload)
        signature = _b64decode(encoded_signature)
        session_id, raw_expiration = payload.decode("ascii").rsplit(".", 1)
        expires_at = int(raw_expiration)
    except (ValueError, UnicodeDecodeError):
        return None
    expected = hmac.new(
        settings.browser_session_secret.encode("utf-8"), payload, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected) or expires_at <= int(time.time()):
        return None
    return session_id or None


def _normalized_origin(value: str | None) -> str | None:
    if not value or value == "null":
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def origin_is_allowed(
    origin: str | None,
    host: str | None,
    settings: Settings,
    *,
    allow_missing_in_development: bool = True,
) -> bool:
    normalized = _normalized_origin(origin)
    if normalized is None:
        return allow_missing_in_development and not settings.public_mode and not origin
    configured = {_normalized_origin(item) for item in settings.browser_allowed_origins}
    configured.discard(None)
    if configured:
        return normalized in configured
    return not settings.public_mode and bool(host) and normalized.split("://", 1)[1] == host.lower()


def require_http_origin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if not origin_is_allowed(
        request.headers.get("origin"),
        request.headers.get("host"),
        settings,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin is not allowed")


def browser_principal(request: Request) -> str:
    settings: Settings = request.app.state.settings
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        require_http_origin(request)
    if not settings.public_mode:
        client_host = request.client.host if request.client else "local"
        return f"development:{client_host}"
    session_id = verify_session(settings, request.cookies.get(SESSION_COOKIE))
    if session_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bella login required")
    return session_id


def websocket_principal(websocket: WebSocket) -> str | None:
    settings: Settings = websocket.app.state.settings
    if not origin_is_allowed(
        websocket.headers.get("origin"), websocket.headers.get("host"), settings
    ):
        return None
    if not settings.public_mode:
        client_host = websocket.client.host if websocket.client else "local"
        return f"development:{client_host}"
    return verify_session(settings, websocket.cookies.get(SESSION_COOKIE))


def password_matches(settings: Settings, submitted: str) -> bool:
    configured = settings.browser_access_password
    return bool(configured) and hmac.compare_digest(configured, submitted)
