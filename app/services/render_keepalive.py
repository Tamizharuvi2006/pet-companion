"""Optional self-ping for keeping a Render Free web service active."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)


def health_url(external_url: str | None) -> str | None:
    """Return the service's HTTPS health URL, rejecting malformed overrides."""
    if not external_url:
        return None
    try:
        parsed = urlsplit(external_url.strip())
        _ = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return urlunsplit(("https", parsed.netloc, "/health", "", ""))


async def _keepalive_loop(
    url: str,
    interval_seconds: int,
    client: httpx.AsyncClient,
    sleeper: Callable[[float], Awaitable[None]],
) -> None:
    while True:
        await sleeper(interval_seconds)
        try:
            response = await client.get(url)
            response.raise_for_status()
            logger.debug("Render keepalive health request succeeded")
        except httpx.HTTPError as error:
            logger.warning(
                "Render keepalive health request failed: %s",
                type(error).__name__,
            )


async def run_render_keepalive(
    external_url: str | None,
    interval_seconds: int,
    *,
    client: httpx.AsyncClient | None = None,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Ping /health at an opt-in interval; cancellation stops the task cleanly."""
    url = health_url(external_url)
    if interval_seconds <= 0 or url is None:
        return

    if client is None:
        async with httpx.AsyncClient(timeout=5.0) as owned_client:
            await _keepalive_loop(url, interval_seconds, owned_client, sleeper)
    else:
        await _keepalive_loop(url, interval_seconds, client, sleeper)


def start_render_keepalive(
    external_url: str | None, interval_seconds: int
) -> asyncio.Task[None] | None:
    """Start the optional loop only when Render URL and a positive interval exist."""
    if interval_seconds <= 0:
        return None
    if health_url(external_url) is None:
        logger.warning(
            "Render keepalive requested but RENDER_EXTERNAL_URL is missing or invalid; disabled"
        )
        return None
    logger.info(
        "Render keepalive enabled interval_seconds=%s endpoint=/health",
        interval_seconds,
    )
    return asyncio.create_task(
        run_render_keepalive(external_url, interval_seconds),
        name="render-health-keepalive",
    )
