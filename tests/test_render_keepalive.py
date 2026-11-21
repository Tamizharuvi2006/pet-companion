import asyncio

import httpx

from app.services.render_keepalive import health_url, run_render_keepalive


def test_health_url_uses_only_render_https_origin() -> None:
    assert health_url("https://bella.onrender.com") == "https://bella.onrender.com/health"
    assert health_url("http://bella.onrender.com") is None
    assert health_url("https://user:secret@bella.onrender.com") is None
    assert health_url("https://bella.onrender.com/path") is None
    assert health_url(None) is None


def test_keepalive_pings_health_at_configured_interval() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def get(self, url: str) -> httpx.Response:
            self.urls.append(url)
            return httpx.Response(200, request=httpx.Request("GET", url))

    client = FakeClient()
    sleep_intervals: list[float] = []

    async def sleeper(seconds: float) -> None:
        sleep_intervals.append(seconds)
        if len(sleep_intervals) > 1:
            raise asyncio.CancelledError

    try:
        asyncio.run(
            run_render_keepalive(
                "https://bella.onrender.com",
                20,
                client=client,  # type: ignore[arg-type]
                sleeper=sleeper,
            )
        )
    except asyncio.CancelledError:
        pass

    assert client.urls == ["https://bella.onrender.com/health"]
    assert sleep_intervals == [20, 20]


def test_keepalive_is_inactive_when_interval_is_zero() -> None:
    async def fail_if_called(_seconds: float) -> None:
        raise AssertionError("disabled keepalive must not sleep or make requests")

    asyncio.run(
        run_render_keepalive(
            "https://bella.onrender.com", 0, sleeper=fail_if_called
        )
    )
