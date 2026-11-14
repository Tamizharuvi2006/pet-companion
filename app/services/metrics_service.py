import asyncio
from collections import Counter
from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class MetricsService:
    """Small dependency-free Prometheus-compatible metrics registry."""

    started_at: float = field(default_factory=perf_counter)
    requests: Counter[tuple[str, int]] = field(default_factory=Counter)
    request_seconds: float = 0.0
    active_websockets: int = 0
    total_websockets: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def record_request(self, method: str, status_code: int, duration: float) -> None:
        async with self._lock:
            self.requests[(method, status_code)] += 1
            self.request_seconds += duration

    async def websocket_opened(self) -> None:
        async with self._lock:
            self.active_websockets += 1
            self.total_websockets += 1

    async def websocket_closed(self) -> None:
        async with self._lock:
            self.active_websockets = max(0, self.active_websockets - 1)

    async def render(self) -> str:
        async with self._lock:
            lines = [
                "# HELP bella_process_uptime_seconds Seconds since application startup.",
                "# TYPE bella_process_uptime_seconds gauge",
                f"bella_process_uptime_seconds {perf_counter() - self.started_at:.6f}",
                "# HELP bella_http_requests_total HTTP requests completed by method and status.",
                "# TYPE bella_http_requests_total counter",
            ]
            lines.extend(
                f'bella_http_requests_total{{method="{method}",status="{status}"}} {count}'
                for (method, status), count in sorted(self.requests.items())
            )
            lines.extend(
                [
                    "# HELP bella_http_request_duration_seconds_total Total HTTP request duration.",
                    "# TYPE bella_http_request_duration_seconds_total counter",
                    f"bella_http_request_duration_seconds_total {self.request_seconds:.6f}",
                    "# HELP bella_websocket_connections Active and total WebSocket connections.",
                    "# TYPE bella_websocket_connections gauge",
                    f'bella_websocket_connections{{state="active"}} {self.active_websockets}',
                    f'bella_websocket_connections{{state="total"}} {self.total_websockets}',
                ]
            )
            return "\n".join(lines) + "\n"
