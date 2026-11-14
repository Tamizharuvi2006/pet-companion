import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class DeviceRecord:
    device_id: str
    connected: bool = False
    firmware_version: str = "unknown"
    state: str = "DISCONNECTED"
    capabilities: dict[str, Any] = field(default_factory=dict)
    sensors: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: str | None = None
    last_error: str | None = None


class DeviceRegistry:
    """Process-local device presence and reported health."""

    def __init__(self) -> None:
        self._records: dict[str, DeviceRecord] = {}
        self._lock = asyncio.Lock()

    async def connected(
        self,
        device_id: str,
        firmware_version: str,
        capabilities: dict[str, Any],
        sensors: dict[str, Any],
    ) -> bool:
        async with self._lock:
            existing = self._records.get(device_id)
            if existing is not None and existing.connected:
                return False
            self._records[device_id] = DeviceRecord(
                device_id=device_id,
                connected=True,
                firmware_version=firmware_version,
                state="IDLE",
                capabilities=dict(capabilities),
                sensors=dict(sensors),
                last_heartbeat=_now(),
            )
            return True

    async def heartbeat(
        self,
        device_id: str,
        *,
        state: str | None = None,
        sensors: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            record = self._records.get(device_id)
            if record is None:
                return
            record.last_heartbeat = _now()
            if state is not None:
                record.state = state
            if sensors is not None:
                record.sensors = dict(sensors)

    async def failed(self, device_id: str, error: str) -> None:
        async with self._lock:
            record = self._records.get(device_id)
            if record is not None:
                record.last_error = error[:160]

    async def camera_snapshot(self, device_id: str, size_bytes: int) -> None:
        async with self._lock:
            record = self._records.setdefault(device_id, DeviceRecord(device_id=device_id))
            record.last_heartbeat = _now()
            record.sensors["camera_available"] = True
            record.sensors["camera_last_snapshot_bytes"] = size_bytes

    async def disconnected(self, device_id: str) -> None:
        async with self._lock:
            record = self._records.get(device_id)
            if record is not None:
                record.connected = False
                record.state = "DISCONNECTED"
                record.last_heartbeat = _now()

    async def snapshot(self, device_id: str | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            records = [self._records[device_id]] if device_id in self._records else [] if device_id else list(self._records.values())
            return [asdict(record) for record in records]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
