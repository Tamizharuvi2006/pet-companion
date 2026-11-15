import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from time import monotonic
import uuid


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
    face_expression: str = 'idle'
    face_sequence: int = -1
    last_touch: int | None = None
    command_status: str | None = None
    command_id: str | None = None


class DeviceRegistry:
    """Process-local device presence and reported health."""

    def __init__(self) -> None:
        self._records: dict[str, DeviceRecord] = {}
        self._lock = asyncio.Lock()
        self._commands: dict[str, dict[str, Any]] = {}
        self._command_deadlines: dict[str, float] = {}

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
                record.face_expression = 'offline'
                self._commands.pop(device_id, None)
                if record.command_status == 'pending':
                    record.command_status = 'disconnected'

    async def command(self, device_id: str, expression: str, duration_ms: int) -> str | None:
        async with self._lock:
            record = self._records.get(device_id)
            if record is None or not record.connected or not record.capabilities.get('face_protocol_v1'):
                return None
            command_id = uuid.uuid4().hex
            # Latest-event semantics: one waiting command per connected device.
            self._commands[device_id] = {'type': 'face_command', 'version': 1,
                'face_version': 1, 'command_id': command_id, 'expression': expression,
                'duration_ms': duration_ms, 'priority': 10, 'return_to_idle': True,
                'expires': monotonic()+15}
            record.command_status = 'pending'
            record.command_id = command_id
            self._command_deadlines[device_id] = monotonic()+15
            return command_id

    async def take_command(self, device_id: str) -> dict[str, Any] | None:
        async with self._lock:
            command = self._commands.pop(device_id, None)
            if command is None:
                return None
            expires = command.pop('expires')
            if monotonic() > expires:
                self._records[device_id].command_status = 'expired'
                return None
            return command

    async def acknowledge(self, device_id: str, command_id: str) -> None:
        async with self._lock:
            record = self._records[device_id]
            if record.command_id == command_id and record.command_status == 'pending':
                record.command_status = 'accepted_by_engine'

    async def face_report(self, device_id: str, expression: str, sequence: int, touch_pad: int | None) -> None:
        async with self._lock:
            record = self._records[device_id]
            if sequence <= record.face_sequence:
                return
            record.face_sequence = sequence
            record.face_expression = expression
            if touch_pad is not None:
                record.last_touch = touch_pad

    async def snapshot(self, device_id: str | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            for key, deadline in list(self._command_deadlines.items()):
                if monotonic() > deadline:
                    record = self._records.get(key)
                    if record and record.command_status == 'pending':
                        record.command_status = 'ack_timeout'
                    self._command_deadlines.pop(key, None)
                    self._commands.pop(key, None)
            records = [self._records[device_id]] if device_id in self._records else [] if device_id else list(self._records.values())
            return [asdict(record) for record in records]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
